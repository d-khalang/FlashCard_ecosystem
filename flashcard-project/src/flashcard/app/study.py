"""
Study use cases for the Mini App: deliver a card without a Telegram message, resume it,
grade it (with one level of undo) and refresh a section of it.

Selection, generation and quota are ReviewUseCases' and QuotaPolicy's; this class only
adds what the app needs on top (docs/mini-app.md):

- A card delivered here gets a negative random delivery id in place of a Telegram message id,
  so the same grade-once code applies (`pending_message_id`) and no id can collide with a
  real message. It does not set the legacy `has_pending` pause flag.
- The card the user has not graded yet (`current_review` plus its stored card) is resumed
  rather than replaced, so a double tap or a reload never delivers two cards.
- Callers own presentation and the prepare-ahead slot (`miniapp/prefetch.py`).
"""
import asyncio
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Awaitable, Callable, Optional, Union, get_args

from bson import ObjectId

from flashcard.app.cards import card_settings
from flashcard.app.quota import QuotaExceeded, QuotaPolicy, Usage
from flashcard.app.review import (
    CardGenerationFailed, CardNotFound, GenerationGate, GenerationHeld, Graded, GradeResult, NoCandidate,
    NotPending, ReviewReady, ReviewUseCases, Throttled,
)
from flashcard.app.shadow import shadow_write
from flashcard.schemas.expression import (
    CardSectionName, Direction, Expression, ExpressionCard, StoredCard,
)
from flashcard.schemas.user import LastAppGrade, UserDB, UserId
from flashcard.services.expression import ExpressionService, WordCounts
from flashcard.services.llm.llm import LLMService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService
from flashcard.utils.logger import get_logger
from flashcard.utils.time import now_utc

logger = get_logger(__name__)

# Server-side limit on one generation, whatever the providers' own timeouts add up to.
GENERATION_TIMEOUT_SECONDS = 30.0
# The last app grade can be undone for this long.
UNDO_WINDOW = timedelta(hours=1)
# A resumed card whose stored card is older than its delivery by more than this came from storage.
FROM_STORAGE_AFTER = timedelta(seconds=60)
# Delivery ids are negative integers within JavaScript's safe integer range.
MAX_DELIVERY_ID = 2**53 - 1


def new_delivery_id() -> int:
    """A random id in [-(2**53 - 1), -1]: never a Telegram message id (those are positive)."""
    return -(secrets.randbelow(MAX_DELIVERY_ID) + 1)


@dataclass(frozen=True)
class StudyCard:
    """A delivered card as the app shows it."""
    delivery_id: int
    expression_id: str
    value: str
    direction: Direction
    card: ExpressionCard
    from_storage: bool
    older_settings: bool


@dataclass(frozen=True)
class CurrentState:
    card: Optional[StudyCard]
    undo_available: bool


@dataclass(frozen=True)
class Delivered:
    card: StudyCard


@dataclass(frozen=True)
class GenerationFailed:
    """No card could be made in time (provider error, invalid answer, or the 30 s limit)."""
    # The LLM answered but could not make sense of the word (which is now deferred), as opposed
    # to an error or timeout: trying the next word may work.
    unclear: bool = False


NextResult = Union[Delivered, NoCandidate, QuotaExceeded, GenerationFailed, Throttled]
# What a prepare-ahead task ends with; only a ReviewReady is worth keeping.
PrepareOutcome = Union[ReviewReady, NoCandidate, QuotaExceeded, GenerationFailed, Throttled]
PreparedSource = Callable[[], Awaitable[Optional[ReviewReady]]]


@dataclass(frozen=True)
class Undone:
    card: StudyCard


@dataclass(frozen=True)
class NothingToUndo:
    pass


UndoResult = Union[Undone, NothingToUndo]


@dataclass(frozen=True)
class Refreshed:
    card: StudyCard


RefreshResult = Union[Refreshed, NotPending, QuotaExceeded, GenerationFailed, Throttled]


@dataclass(frozen=True)
class Overview:
    user: UserDB
    quota: Usage
    words: WordCounts
    # A delivered card is waiting for a grade (the same rule as resuming it).
    pending: bool


class _UserLocks:
    """One asyncio lock per user, dropped again when nobody holds or awaits it."""

    def __init__(self) -> None:
        self._entries: dict[UserId, list] = {}  # user -> [lock, holders and waiters]

    @asynccontextmanager
    async def hold(self, user_id: UserId):
        entry = self._entries.setdefault(user_id, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._entries.pop(user_id, None)


class StudyUseCases:
    def __init__(
        self,
        review_use_cases: ReviewUseCases,
        expression_service: ExpressionService,
        user_service: UserService,
        quota: QuotaPolicy,
        llm_service: LLMService,
        review_state: ReviewStateStore,
    ):
        self.review = review_use_cases
        self.expressions = expression_service
        self.users = user_service
        self.quota = quota
        self.llm = llm_service
        self.review_state = review_state
        # Delivery and refresh may wait for an LLM; grade and undo are quick and never wait for it.
        self._delivery_locks = _UserLocks()
        self._grade_locks = _UserLocks()

    async def overview(self, user_id: UserId) -> Overview:
        """What the Today screen shows: settings, today's usage and the word counts."""
        user = await self.users.get_user(user_id)
        return Overview(
            user=user,
            quota=self.quota.usage(user, "cards"),
            words=await self.expressions.count_words(user_id),
            pending=await self._resumable(user_id, user) is not None,
        )

    async def current(self, user_id: UserId) -> CurrentState:
        """The delivered card still waiting for a grade (from the app or the bot), if any."""
        user = await self.users.get_user(user_id)
        return CurrentState(card=await self._resumable(user_id, user), undo_available=_undo_available(user))

    async def prepare(
        self, user_id: UserId, before_generation: Optional[GenerationGate] = None,
    ) -> PrepareOutcome:
        """
        Pick and generate the next card without delivering it (the prepare-ahead task).
        Nothing is stored or counted: an abandoned card costs one LLM call and no quota.
        `before_generation` is asked right before the LLM call (see ReviewUseCases.prepare_next).
        """
        try:
            result = await asyncio.wait_for(
                self.review.prepare_next(user_id, before_generation=before_generation, any_stored_when_over_quota=True),
                GENERATION_TIMEOUT_SECONDS,
            )
        except CardGenerationFailed:
            logger.warning("The LLM could not make a card for user %s", user_id)
            return GenerationFailed(unclear=True)
        except Exception:
            logger.warning("Card generation failed for user %s", user_id, exc_info=True)
            return GenerationFailed()
        return GenerationFailed() if isinstance(result, GenerationHeld) else result

    async def next(
        self, user_id: UserId, take_prepared: Optional[PreparedSource] = None,
        before_generation: Optional[GenerationGate] = None,
    ) -> NextResult:
        """
        Deliver the next card. If one is already waiting for a grade, that same card is
        returned (a double tap is safe). Otherwise a card prepared ahead is used while it is
        still valid; if not, a new one is generated (`before_generation` is asked right before
        each LLM call). A word the LLM cannot make sense of is deferred; the next word is then
        tried once before giving up.
        """
        async with self._delivery_locks.hold(user_id):
            user = await self.users.get_user(user_id)
            waiting = await self._resumable(user_id, user)
            if waiting is not None:
                return Delivered(waiting)

            ready: Optional[ReviewReady] = None
            if take_prepared is not None:
                prepared = await take_prepared()
                if prepared is not None:
                    ready = await self._still_valid(user_id, user, prepared)
            if ready is None:
                outcome = await self.prepare(user_id, before_generation)
                if isinstance(outcome, GenerationFailed) and outcome.unclear:
                    outcome = await self.prepare(user_id, before_generation)
                if not isinstance(outcome, ReviewReady):
                    return outcome
                ready = outcome
            return Delivered(await self._deliver(user_id, ready))

    async def grade(
        self, user_id: UserId, expression_id: str, grade: int, direction: Direction, *, delivery_id: int,
    ) -> GradeResult:
        """
        Grade the card delivered as `delivery_id`, once, as ReviewUseCases.grade does for a message
        id, and remember what undo needs. Raises ValueError for an out-of-range grade or direction.
        `expression_id` comes from the client: it is only used scoped to this user.
        """
        if not isinstance(expression_id, str) or not ObjectId.is_valid(expression_id):
            return CardNotFound()
        async with self._grade_locks.hold(user_id):
            check = await self.expressions.check_gradable(
                user_id, expression_id, grade, direction, message_id=delivery_id)
            if check == "not_found":
                return CardNotFound()
            if check == "not_pending":
                return NotPending()

            user = await self.users.get_user(user_id)
            sent_at = await self._sent_at(user_id, user, expression_id, delivery_id)

            reviewed_at = await self.review_state.record_reviewed(user_id)
            await shadow_write(
                self.review_state.record_graded(user_id, expression_id, direction),
                f"record_graded user={user_id} expression={expression_id}",
            )
            # The card write comes last, as in ReviewUseCases.grade: it is what stops a retry.
            outcome = await self.expressions.grade_expression(
                user_id, expression_id, grade, direction, message_id=delivery_id, keep_undo=True)
            if outcome == "not_found":
                return CardNotFound()
            if outcome == "not_pending":
                return NotPending()

            # Undo is a convenience: failing to remember it must not fail a grade that happened.
            await shadow_write(
                self.review_state.record_app_grade(user_id, LastAppGrade(
                    expression_id=expression_id,
                    direction=direction,
                    delivery_id=delivery_id,
                    previous_reviewed_at=user.last_reviewed_at,
                    sent_at=sent_at,
                    # The time written to the user: undo restores the interval only while it is unchanged.
                    graded_at=reviewed_at,
                )),
                f"record_app_grade user={user_id} expression={expression_id}",
            )
            return Graded()

    async def undo(self, user_id: UserId) -> UndoResult:
        """
        Undo the last grade made in the app, if it is recent and nothing touched the card since
        (see ExpressionService.undo_grade). Usage is not refunded.
        """
        async with self._grade_locks.hold(user_id):
            user = await self.users.get_user(user_id)
            last = user.last_app_grade
            if last is None or not _undo_available(user):
                return NothingToUndo()

            expression = await self.expressions.get_expression(user_id, last.expression_id)
            if expression is None or expression.last_card is None:
                await self.review_state.clear_app_grade(user_id, last.delivery_id)
                return NothingToUndo()
            outcome = await self.expressions.undo_grade(user_id, last.expression_id, last.delivery_id)
            if outcome != "undone":
                # Sent again or graded elsewhere: this hint can never apply, stop offering it.
                await self.review_state.clear_app_grade(user_id, last.delivery_id)
                return NothingToUndo()

            await self.review_state.restore_after_undo(user_id, last)
            restored = await self.expressions.get_expression(user_id, last.expression_id) or expression
            return Undone(_study_card(
                restored, delivery_id=last.delivery_id, direction=last.direction, sent_at=last.sent_at,
                settings=card_settings(user),
            ))

    async def refresh_section(
        self, user_id: UserId, delivery_id: int, section: CardSectionName,
        before_generation: Optional[GenerationGate] = None,
    ) -> RefreshResult:
        """
        Write one section of the pending card again (definition, translations or example). Costs
        one card; the card is unchanged on any failure.
        """
        if section not in get_args(CardSectionName):
            raise ValueError(f"Unknown card section: {section!r}")
        async with self._delivery_locks.hold(user_id):
            user = await self.users.get_user(user_id)
            review = user.current_review
            if review is None or review.message_id != delivery_id:
                return NotPending()
            expression = await self.expressions.get_expression(user_id, review.expression_id)
            if (expression is None or expression.last_card is None
                    or expression.pending_message_id != delivery_id):
                return NotPending()

            quota = self.quota.check(user, "cards")
            if isinstance(quota, QuotaExceeded):
                return quota

            if before_generation is not None:
                refused = before_generation()
                if isinstance(refused, GenerationHeld):
                    return GenerationFailed()
                if refused is not None:
                    return refused

            stored = expression.last_card
            try:
                regenerated = await asyncio.wait_for(
                    self.llm.generate_card_section(
                        section,
                        expression=expression.value,
                        level=stored.settings.level,
                        definition=stored.card.learning_definition,
                        translations=stored.card.translations,
                        example=stored.card.learning_example,
                    ),
                    GENERATION_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.warning("Section %s refresh failed for expression %s", section, expression.id,
                               exc_info=True)
                return GenerationFailed()

            merged = await self.expressions.merge_card_section(
                user_id, expression.id, delivery_id, section, regenerated)
            if not merged:
                return NotPending()
            await self.quota.record(user_id, "cards", quota)

            refreshed = await self.expressions.get_expression(user_id, expression.id) or expression
            return Refreshed(_study_card(
                refreshed, delivery_id=delivery_id, direction=review.direction, sent_at=review.sent_at,
                settings=card_settings(user),
            ))

    async def _resumable(self, user_id: UserId, user: UserDB) -> Optional[StudyCard]:
        """The current review as a card, if its expression still has the card to show and is still pending."""
        review = user.current_review
        if review is None:
            return None
        expression = await self.expressions.get_expression(user_id, review.expression_id)
        if (expression is None or expression.last_card is None
                or expression.pending_message_id != review.message_id):
            return None
        return _study_card(
            expression, delivery_id=review.message_id, direction=review.direction, sent_at=review.sent_at,
            settings=card_settings(user),
        )

    async def _still_valid(self, user_id: UserId, user: UserDB, ready: ReviewReady) -> Optional[ReviewReady]:
        """
        A card prepared earlier, if it may still be delivered: its expression is active and past its
        cooldown, its settings and review mode still match the user's, and quota still allows
        a fresh card.
        None means: prepare again (which also handles falling back to the stored card).
        """
        if not await self.expressions.still_due(user_id, ready.expression_id):
            return None
        if ready.from_storage:
            return None  # only fresh cards are kept ahead; a stored one costs nothing to derive again
        if ready.settings != card_settings(user):
            return None
        if ready.direction == "reverse" and user.review_mode != "dual":
            return None
        quota = self.quota.check(user, "cards")
        if isinstance(quota, QuotaExceeded):
            return None
        return replace(ready, quota=quota)

    async def _deliver(self, user_id: UserId, ready: ReviewReady) -> StudyCard:
        """Record a delivery: the card as pending under a new delivery id, the current review, usage."""
        delivery_id = new_delivery_id()
        stored = None if ready.from_storage else StoredCard(
            card=ready.card, settings=ready.settings, generated_at=now_utc())
        await self.expressions.update_expression_sent(
            ready.expression_id, delivery_id, last_card=stored, user_id=user_id)
        # Not a shadow write: resuming the card depends on it. No mark_pending either (legacy flag).
        await self.review_state.record_sent(user_id, ready.expression_id, ready.direction, delivery_id)
        if not ready.from_storage:
            await self.quota.record(user_id, "cards", ready.quota)
        return StudyCard(
            delivery_id=delivery_id,
            expression_id=ready.expression_id,
            value=ready.value,
            direction=ready.direction,
            card=ready.card,
            from_storage=ready.from_storage,
            older_settings=ready.older_settings,
        )

    async def _sent_at(self, user_id: UserId, user: UserDB, expression_id: str, delivery_id: int):
        review = user.current_review
        if review is not None and review.message_id == delivery_id:
            return review.sent_at
        # Not the current review any more: the card's own send time is the best reference.
        expression = await self.expressions.get_expression(user_id, expression_id)
        return (expression.last_activity_at if expression is not None else None) or now_utc()


def _undo_available(user: UserDB) -> bool:
    last = user.last_app_grade
    return last is not None and now_utc() - last.graded_at <= UNDO_WINDOW


def _direction(stored: str) -> Direction:
    """Reviews backfilled from legacy fields have no direction; they count as forward."""
    return "reverse" if stored == "reverse" else "forward"


def _study_card(
    expression: Expression, *, delivery_id: int, direction: str, sent_at, settings,
) -> StudyCard:
    """A pending card read back from its expression's stored card."""
    stored = expression.last_card
    return StudyCard(
        delivery_id=delivery_id,
        expression_id=expression.id,
        value=expression.value,
        direction=_direction(direction),
        card=stored.card,
        from_storage=sent_at - stored.generated_at > FROM_STORAGE_AFTER,
        older_settings=stored.settings != settings,
    )
