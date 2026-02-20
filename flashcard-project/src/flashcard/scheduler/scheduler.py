import asyncio
import html
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot

from flashcard.schemas.user import UserDB
from flashcard.schemas.languages import get_language_flag
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from flashcard.services.consumption import ConsumptionService
from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression import format_review_message
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.utils.logger import get_logger, notify_admin_with_trace
from flashcard.settings import settings
from flashcard.utils.time import now_utc, iso_z

logger = get_logger(__name__)

# Scheduler configuration
SCHEDULER_CHECK_INTERVAL_SECONDS = settings.SCHEDULER_CHECK_INTERVAL_SECONDS

from flashcard.schemas.defaults import DEFAULT_LANG_LEVEL, DEFAULT_LANG_1_CODE, DEFAULT_LANG_1_LABEL, DEFAULT_SCHEDULER_INTERVAL_MINUTES


async def find_users_due_for_review(user_service: UserService) -> list[UserDB]:
    """
    Finds active users who are due for a review.
    
    Optimized with MongoDB-level date filtering to reduce fetched documents,
    followed by Python-side per-user interval checking for accuracy.
    
    Returns:
        List of UserDB objects for users who meet all criteria:
        - is_active == True (scheduler not paused)
        - has_pending == False (no ungraded flashcard)
        - last_reviewed_at + review_interval_minutes < now (or never reviewed)
    """
    
    
    now = now_utc()
    
    # Use minimum possible interval (e.g., 30 minutes) as a conservative cutoff for MongoDB query
    # This filters out definitely-not-due users at database level for performance
    # We still check exact intervals per-user in Python since intervals vary by user
    # TODO: must be dynamic based on user's review_interval_minutes
    min_interval_minutes = DEFAULT_SCHEDULER_INTERVAL_MINUTES
    cutoff_time = iso_z(now - timedelta(minutes=min_interval_minutes))
    
    # Optimized MongoDB query: pre-filter by approximate timing
    users_cursor = user_service.cols['users'].find({
        "is_active": True,
        "has_pending": False,
        "$or": [
            {"last_reviewed_at": None},  # Never reviewed
            {"last_reviewed_at": {"$lt": cutoff_time}}  # Reviewed before cutoff
        ]
    })
    
    users_due = []
    async for user_doc in users_cursor:
        # Parse to UserDB for type safety
        user = UserDB.model_validate(user_doc)
        
        # Check if enough time has passed since last review
        last_reviewed = user.last_reviewed_at
        
        if not last_reviewed:
            # Never reviewed, they're due
            users_due.append(user)
            continue
        
        # Parse timestamp and check user's specific interval
        interval_minutes = user.review_interval_minutes
        last_reviewed_dt = datetime.fromisoformat(last_reviewed.replace('Z', '+00:00'))
        
        # Calculate time elapsed
        elapsed_seconds = (now - last_reviewed_dt).total_seconds()
        
        if elapsed_seconds >= interval_minutes * 60:
            users_due.append(user)
    
    return users_due


async def send_scheduled_review(
    bot: Bot,
    user: UserDB,
    expression_service: ExpressionService,
    llm_service: LLMService,
    user_service: UserService,
    consumption_service: ConsumptionService,
) -> None:
    """
    Sends a scheduled review to a user.
    Replicates the /get command logic but uses bot.send_message instead of message.answer.
    Uses user preferences for language and level.
    
    Raises exceptions on failure (caught by per-user error handler in scheduler loop).
    """
    user_id = user.user_id
    # 1. Get review candidate
    result = await expression_service.get_review_candidate(user_id)
    
    if not result:
        # No cards to review, skip silently
        logger.debug(f"No review candidate for user {user_id}")
        return
    
    candidate = result["doc"]
    direction = result.get("direction", "forward")
    
    # 2. Generate card content using user preferences
    card = await llm_service.generate_expression_card(
        raw=candidate['value'],
        level=user.target_level or DEFAULT_LANG_LEVEL,
        lang1_code=user.primary_language or DEFAULT_LANG_1_CODE,
        lang2_code=user.secondary_language,
        lang1_label=get_language_flag(user.primary_language),  
        lang2_label=get_language_flag(user.secondary_language)  
    )
    
    # 3. Format message
    text = format_review_message(card, candidate['value'], direction=direction)
    
    # 4. Get keyboard
    keyboard = get_review_keyboard(str(candidate['_id']), direction=direction)
    
    # 5. Send via bot
    sent_msg = await bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=keyboard
    )
    
    # 6. Update database
    await expression_service.update_expression_sent(str(candidate['_id']), sent_msg.message_id)
    await user_service.update_user_last_push(user_id)
    
    # Track consumption
    await consumption_service.increment(user_id, "cards_generated", uses_own_key=user.api_config is not None)
    
    logger.info(f"Scheduled review sent to user {user_id}: {candidate['value']}")


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


async def scheduler_loop(
    bot: Bot,
    logger_bot: Bot,
    expression_service: ExpressionService,
    user_service: UserService,
    consumption_service: ConsumptionService,
    llm_service: LLMService,
    admin_id: int
) -> None:
    """
    Main scheduler loop that runs indefinitely.
    
    Every SCHEDULER_CHECK_INTERVAL_SECONDS:
    1. Finds users due for review
    2. Sends scheduled reviews with per-user error isolation
    3. Sends admin metrics report
    """
    logger.info(f"Scheduler started. Check interval: {SCHEDULER_CHECK_INTERVAL_SECONDS}s")
    
    while True:
        cycle_start = now_utc()
        successful_ids = []
        failed_details = []
        
        try:
            # Find users who need reviews
            users_to_push = await find_users_due_for_review(user_service)
            logger.info(f"Found {len(users_to_push)} users due for review")
            
            # Process each user with isolated error handling
            for user in users_to_push:
                try:
                    await send_scheduled_review(
                        bot=bot,
                        user=user,
                        expression_service=expression_service,
                        llm_service=llm_service,
                        user_service=user_service,
                        consumption_service=consumption_service,
                    )
                    successful_ids.append(user.user_id)
                    
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
                    await send_admin_metrics(
                        logger_bot=logger_bot,
                        admin_id=admin_id,
                        successful_ids=successful_ids,
                        failed_details=failed_details,
                        total_time=total_time
                    )
                except Exception as e:
                    logger.error(f"Failed to send admin metrics: {e}")
            
        except Exception as e:
            # Catch loop-level errors (e.g., database connection issues)
            logger.error(f"Scheduler loop error: {e}", exc_info=True)
            try:
                error_text = html.escape(f"{type(e).__name__}: {str(e)[:300]}")
                await notify_admin_with_trace(logger_bot, f"🚨 <b>Scheduler Loop Error</b>\n\n{error_text}")
            except Exception as notify_error:
                logger.error(f"Failed to notify admin about scheduler error: {notify_error}")
        
        # Sleep until next cycle
        await asyncio.sleep(SCHEDULER_CHECK_INTERVAL_SECONDS)
