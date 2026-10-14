import asyncio
import html
import uuid
from datetime import timedelta
from typing import Optional
from aiogram import Bot

from flashcard.app.review_schedule import PauseComparison, PauseRule, interval_elapsed, paused
from flashcard.schemas.trace import TraceData
from flashcard.schemas.user import UserDB
from flashcard.app.review import NoCandidate, QuotaExceeded, ReviewUseCases
from flashcard.services.user import UserService
from flashcard.telegram.ui.expression import format_review_message
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.utils.logger import get_logger, notify_admin_with_trace
from flashcard.settings import settings
from flashcard.utils.time import now_utc, iso_z
from flashcard.utils.tracing import set_current_trace, finalize_trace, observe

logger = get_logger(__name__)

# Scheduler configuration
SCHEDULER_CHECK_INTERVAL_SECONDS = settings.SCHEDULER_CHECK_INTERVAL_SECONDS

from flashcard.schemas.defaults import DEFAULT_SCHEDULER_INTERVAL_MINUTES


async def find_users_due_for_review(user_service: UserService, pause_rule: PauseRule = "legacy") -> list[UserDB]:
    """
    Finds active users who are due for a review.

    Optimized with MongoDB-level date filtering to reduce fetched documents,
    followed by Python-side per-user interval checking for accuracy.

    Returns:
        List of UserDB objects for users who meet all criteria:
        - is_active == True (scheduler not paused)
        - not paused by `pause_rule` (legacy: has_pending; current_review: a card
          is waiting and the user has not been seen since it was sent)
        - last_reviewed_at + review_interval_minutes < now (or never reviewed)
    """

    now = now_utc()

    # Use minimum possible interval (e.g., 30 minutes) as a conservative cutoff for MongoDB query
    # This filters out definitely-not-due users at database level for performance
    # We still check exact intervals per-user in Python since intervals vary by user
    min_interval_minutes = DEFAULT_SCHEDULER_INTERVAL_MINUTES
    cutoff_time = iso_z(now - timedelta(minutes=min_interval_minutes))

    # Optimized MongoDB query: pre-filter by approximate timing
    query = {
        "is_active": True,
        "$or": [
            {"last_reviewed_at": None},  # Never reviewed
            {"last_reviewed_at": {"$lt": cutoff_time}}  # Reviewed before cutoff
        ]
    }
    if pause_rule == "legacy":
        query["has_pending"] = False
    # The current_review rule compares two fields per user, so it is checked in Python.
    users_cursor = user_service.cols['users'].find(query)

    users_due = []
    async for user_doc in users_cursor:
        # Parse to UserDB for type safety
        user = UserDB.model_validate(user_doc)
        if not paused(user, pause_rule) and interval_elapsed(user, now):
            users_due.append(user)

    return users_due


async def compare_pause_rules(user_service: UserService) -> PauseComparison:
    """
    Shadow compare for the review-state migration: legacy `has_pending` vs the
    current_review + last_seen_at rule. Reads only; changes nothing.

    Only active users where either rule could pause are read; everyone else agrees.
    """
    comparison = PauseComparison()
    cursor = user_service.cols['users'].find({
        "is_active": True,
        "$or": [{"has_pending": True}, {"current_review": {"$ne": None}}],
    })
    async for user_doc in cursor:
        comparison.add(UserDB.model_validate(user_doc))
    return comparison


async def _log_pause_comparison(user_service: UserService) -> None:
    """Never lets the shadow compare break a scheduler cycle."""
    try:
        comparison = await compare_pause_rules(user_service)
    except Exception:
        logger.warning("Review-state shadow compare failed", exc_info=True)
        return
    counts = " ".join(f"{name}={count}" for name, count in sorted(comparison.counts.items()))
    logger.info(f"Review-state shadow compare: {counts or 'no paused users'}")
    for user_id, result in comparison.mismatches:
        logger.debug(f"Review-state shadow mismatch: user={user_id} {result}")


@observe(name="scheduler.send_scheduled_review", include_output=False)
async def send_scheduled_review(
    bot: Bot,
    user: UserDB,
    review_use_cases: ReviewUseCases,
) -> bool:
    """
    Sends a scheduled review to a user.

    Returns:
        True if a flashcard was actually sent, False if no candidate was available
        or the user is over quota (skipped silently).

    Raises exceptions on failure (caught by per-user error handler in scheduler loop).
    """
    user_id = user.user_id
    result = await review_use_cases.prepare_next(user_id, user=user)

    if isinstance(result, NoCandidate):
        logger.debug(f"No review candidate for user {user_id}")
        return False

    if isinstance(result, QuotaExceeded):
        logger.info(f"Skipping scheduled review for user {user_id} due to quota limits (tier={result.tier})")
        return False

    text = format_review_message(result.card, result.value, direction=result.direction)
    keyboard = get_review_keyboard(result.expression_id, direction=result.direction)
    sent_msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
    await review_use_cases.mark_sent(user_id, result, sent_msg.message_id)

    logger.info(f"Scheduled review sent to user {user_id}: {result.value}")
    return True


async def send_admin_metrics(
    logger_bot: Bot,
    admin_id: int,
    successful_ids: list[str],
    failed_details: list[dict],
    total_time: float
) -> None:
    """
    Sends scheduler cycle metrics to the admin.

    Args:
        logger_bot: Bot instance for sending admin messages
        admin_id: Telegram ID of the admin
        successful_ids: List of user IDs who received reviews successfully
        failed_details: List of dicts with 'user_id' and 'error' keys
        total_time: Total execution time in seconds
    """
    total = len(successful_ids) + len(failed_details)

    # Build report messages (split if needed to avoid Telegram 4096 char limit)
    messages = []

    # Header message
    header = f"📊 <b>Scheduler Cycle Report</b>\n\n"
    header += f"⏱ Execution Time: {total_time:.2f}s\n"
    header += f"👥 Total Users Processed: {total}\n"
    header += f"✅ Successful: {len(successful_ids)}\n"
    header += f"❌ Failed: {len(failed_details)}\n\n"

    current_msg = header

    # Add successful users
    if successful_ids:
        success_text = f"<b>Successful Users:</b>\n" + ", ".join(successful_ids) + "\n\n"
        if len(current_msg + success_text) > 4000:  # Leave margin for safety
            messages.append(current_msg)
            current_msg = success_text
        else:
            current_msg += success_text

    # Add failed users
    if failed_details:
        current_msg += f"<b>Failed Users:</b>\n"
        for failure in failed_details:
            user_id = failure['user_id']
            error = failure['error']
            # Truncate error message to first 100 chars
            error_snippet = error[:300] + "..." if len(error) > 300 else error
            failure_line = f"• {user_id}: {error_snippet}\n"

            # Split message if too long
            if len(current_msg + failure_line) > 3700:
                messages.append(current_msg)
                current_msg = f"<b>Failed Users (continued):</b>\n" + failure_line
            else:
                current_msg += failure_line

    # Add final message
    if current_msg:
        messages.append(current_msg)

    # Send all messages
    for msg in messages:
        await notify_admin_with_trace(logger_bot, msg)

    logger.info(f"Admin metrics sent: {len(successful_ids)} successful, {len(failed_details)} failed")


@observe(name="scheduler.find_users_due_for_review", include_output=False)
async def _observed_find_users_due_for_review(user_service: UserService, pause_rule: PauseRule) -> list[UserDB]:
    return await find_users_due_for_review(user_service, pause_rule)


@observe(name="scheduler.send_admin_metrics", include_output=False)
async def _observed_send_admin_metrics(
    logger_bot: Bot,
    admin_id: int,
    successful_ids: list[str],
    failed_details: list[dict],
    total_time: float
) -> None:
    await send_admin_metrics(
        logger_bot=logger_bot,
        admin_id=admin_id,
        successful_ids=successful_ids,
        failed_details=failed_details,
        total_time=total_time,
    )


async def scheduler_loop(
    bot: Bot,
    logger_bot: Bot,
    user_service: UserService,
    review_use_cases: ReviewUseCases,
    admin_id: int,
    pause_rule: PauseRule = "legacy",
) -> None:
    """
    Main scheduler loop that runs indefinitely.

    Every SCHEDULER_CHECK_INTERVAL_SECONDS:
    1. Finds users due for review
    2. Sends scheduled reviews with per-user error isolation
    3. Sends admin metrics report

    On consecutive failures: backs off exponentially (30s → 60s → 120s → 5min cap).
    On success: resets to normal interval.
    """
    logger.info(f"Scheduler started. Check interval: {SCHEDULER_CHECK_INTERVAL_SECONDS}s, pause rule: {pause_rule}")

    consecutive_failures = 0
    PER_USER_TIMEOUT = 20  # seconds — don't let one user block the cycle

    while True:
        cycle_start = now_utc()
        trace = TraceData(
            trace_id=str(uuid.uuid4()),
            timestamp=iso_z(cycle_start),
            update_type="scheduler",
            text=f"interval_seconds={SCHEDULER_CHECK_INTERVAL_SECONDS}",
            spans=[],
        )
        token = set_current_trace(trace)
        has_error = False
        trace_error_msg = None
        successful_ids = []
        failed_details = []

        try:
            # Find users who need reviews
            users_to_push = await _observed_find_users_due_for_review(user_service, pause_rule)
            logger.info(f"Found {len(users_to_push)} users due for review")
            await _log_pause_comparison(user_service)

            # Process each user with isolated error handling + per-user timeout
            for user in users_to_push:
                try:
                    sent = await asyncio.wait_for(
                        send_scheduled_review(
                            bot=bot,
                            user=user,
                            review_use_cases=review_use_cases,
                        ),
                        timeout=PER_USER_TIMEOUT,
                    )
                    if sent:
                        successful_ids.append(user.user_id)

                except asyncio.TimeoutError:
                    error_msg = f"Timed out after {PER_USER_TIMEOUT}s"
                    logger.error(f"Timeout sending review to user {user.user_id}")
                    failed_details.append({
                        "user_id": user.user_id,
                        "error": error_msg
                    })

                except Exception as e:
                    # Log error but continue to next user
                    error_msg = f"{type(e).__name__}: {html.escape(str(e))}"
                    logger.error(f"Failed to send review to user {user.user_id}: {error_msg}")
                    failed_details.append({
                        "user_id": user.user_id,
                        "error": error_msg
                    })

            # Calculate cycle time
            cycle_end = now_utc()
            total_time = (cycle_end - cycle_start).total_seconds()

            # Send admin metrics (only if there were users to process)
            if successful_ids or failed_details:
                try:
                    await _observed_send_admin_metrics(
                        logger_bot=logger_bot,
                        admin_id=admin_id,
                        successful_ids=successful_ids,
                        failed_details=failed_details,
                        total_time=total_time,
                    )
                except Exception as e:
                    logger.error(f"Failed to send admin metrics: {e}")

            # Success — reset backoff
            consecutive_failures = 0

        except Exception as e:
            has_error = True
            trace_error_msg = f"{type(e).__name__}: {str(e)}"
            consecutive_failures += 1

            # Catch loop-level errors (e.g., database connection issues)
            logger.error(f"Scheduler loop error: {e}", exc_info=True)
            try:
                error_text = html.escape(f"{type(e).__name__}: {str(e)[:300]}")
                await notify_admin_with_trace(logger_bot, f"🚨 <b>Scheduler Loop Error</b>\n\n{error_text}")
            except Exception as notify_error:
                logger.error(f"Failed to notify admin about scheduler error: {notify_error}")

        finally:
            finalize_trace(trace, token, cycle_start, has_error, trace_error_msg)

        # Sleep: normal interval on success, exponential backoff on failure
        if consecutive_failures > 0:
            backoff = min(30 * (2 ** (consecutive_failures - 1)), 300)
            logger.warning(f"Scheduler backing off: {backoff}s (failure #{consecutive_failures})")
            await asyncio.sleep(backoff)
        else:
            await asyncio.sleep(SCHEDULER_CHECK_INTERVAL_SECONDS)
