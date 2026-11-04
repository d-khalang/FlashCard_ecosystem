"""
Review use cases: pick the next card, generate it, record its delivery and grade it.

Callers own presentation and delivery: they format the card, send it however
they deliver messages, then report the delivered message back via mark_sent.

Each delivered fresh card is stored on its expression (one card, overwritten).
When generation fails, or the user is over quota, that stored card is sent
instead, free of quota.
"""
import asyncio
from dataclasses import dataclass
from typing import Callable, Optional, Union

from flashcard.app.cards import card_settings, generate_card
from flashcard.app.quota import Allowed, QuotaExceeded, QuotaPolicy
from flashcard.app.shadow import shadow_write
from flashcard.schemas.user import UserId
from flashcard.schemas.expression import CardSettings, Direction, Expression, ExpressionCard, StoredCard
from flashcard.schemas.user import UserDB
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService
from flashcard.utils.logger import get_logger
from flashcard.utils.time import now_utc

logger = get_logger(__name__)

# How long a fresh card may take when a stored one could replace it. Below the 10 s
# handler timeout, whose cancellation no fallback could catch, leaving time to send.
STORED_CARD_AFTER_SECONDS = 8.0


@dataclass(frozen=True)
class ReviewReady:
    expression_id: str
    value: str
    direction: Direction
    card: ExpressionCard
    settings: CardSettings
    # How a fresh card is counted. None: the stored card replaced a generation that
    # failed or was over quota; it is free and not stored again.
    quota: Optional[Allowed]
    # Stored card only: the user's level or translation languages changed since.
    older_settings: bool = False

    @property
    def from_storage(self) -> bool:
        return self.quota is None


@dataclass(frozen=True)
class NoCandidate:
    pass


@dataclass(frozen=True)
class Throttled:
    """Generation was not started: the caller's allowance for LLM calls is used up."""
    retry_after: int  # seconds


@dataclass(frozen=True)
class GenerationHeld:
    """Generation was not started: a recent failure keeps it paused."""


# Asked right before an LLM call starts; anything but None stops the call and is the result.
# The Mini App uses it to charge its allowance only for calls that really happen.
GenerationGate = Callable[[], Union[None, Throttled, GenerationHeld]]

PrepareResult = Union[ReviewReady, NoCandidate, QuotaExceeded, Throttled, GenerationHeld]


class CardGenerationFailed(RuntimeError):
    """The LLM answered but could not make a card, and none is stored."""


@dataclass(frozen=True)
class Graded:
    pass


@dataclass(frozen=True)
class CardNotFound:
    pass


@dataclass(frozen=True)
class NotPending:
    """This message is no longer waiting for a grade: a repeated tap, or a newer send replaced it."""


GradeResult = Union[Graded, CardNotFound, NotPending]


class ReviewUseCases:
    def __init__(
        self,
        expression_service: ExpressionService,
        user_service: UserService,
        quota: QuotaPolicy,
        llm_service: LLMService,
        review_state: ReviewStateStore,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.quota = quota
        self.llm = llm_service
        self.review_state = review_state

    async def prepare_next(
        self, user_id: UserId, user: Optional[UserDB] = None, before_generation: Optional[GenerationGate] = None,
    ) -> PrepareResult:
        """
        Pick the highest-priority card and generate its content.
        Pass `user` when already loaded; otherwise it is fetched.
        `before_generation` is asked once the LLM call is certain (a candidate exists and quota
        allows it); a refusal is returned as the result.

        When the LLM cannot make sense of the word and no stored card exists, the word is
        deferred for the 12 h cooldown before CardGenerationFailed is raised, so it does not
        block the user's other cards. A provider error defers nothing.
        """
        if user is None:
            user = await self.users.get_user(user_id)

        candidate = await self.expressions.get_review_candidate(user_id, user.review_mode)
        if candidate is None:
            return NoCandidate()
        expression, direction = candidate.expression, candidate.direction

        settings = card_settings(user)
        quota = self.quota.check(user, "cards")
        if isinstance(quota, QuotaExceeded):
            if expression.last_card is None:
                return quota
            return _from_storage(expression, direction, settings)

        if before_generation is not None:
            refused = before_generation()
            if refused is not None:
                return refused

        # No stored card: nothing to fall back on, so the caller's own timeout decides.
        budget = None if expression.last_card is None else STORED_CARD_AFTER_SECONDS
        try:
            card = await asyncio.wait_for(generate_card(self.llm, expression.value, settings), timeout=budget)
        except Exception:
            if expression.last_card is None:
                raise
            logger.warning("Card generation failed for expression %s; sending its stored card",
                           expression.id, exc_info=True)
            return _from_storage(expression, direction, settings)

        if not card.success:
            if expression.last_card is None:
                await self._defer(user_id, expression.id)
                raise CardGenerationFailed(f"LLM could not make a card for expression {expression.id}")
            logger.warning("LLM could not make a card for expression %s; sending its stored card",
                           expression.id)
            return _from_storage(expression, direction, settings)

        return ReviewReady(
            expression_id=expression.id,
            value=expression.value,
            direction=direction,
            card=card,
            settings=settings,
            quota=quota,
        )

    async def _defer(self, user_id: UserId, expression_id: str) -> None:
        try:
            await self.expressions.defer_review(user_id, expression_id)
        except Exception:
            logger.warning("Could not defer expression %s", expression_id, exc_info=True)

    async def mark_sent(self, user_id: UserId, ready: ReviewReady, message_id: int) -> None:
        """
        Record a delivered review: pending message, review state and usage.
        A fresh card is stored and counted; a stored card is neither.
        """
        last_card = None if ready.from_storage else StoredCard(
            card=ready.card, settings=ready.settings, generated_at=now_utc())
        await self.expressions.update_expression_sent(ready.expression_id, message_id, last_card=last_card)
        await self.review_state.mark_pending(user_id)
        if not ready.from_storage:
            await self.quota.record(user_id, "cards", ready.quota)
        await shadow_write(
            self.review_state.record_sent(user_id, ready.expression_id, ready.direction, message_id),
            f"record_sent user={user_id} expression={ready.expression_id}",
        )

    async def pause_undeliverable(self, user_id: UserId) -> None:
        """The user cannot receive messages (blocked the bot): stop scheduling them, as Pause does."""
        await self.users.set_active(user_id, False)

    async def grade(
        self, user_id: UserId, expression_id: str, grade: int, direction: Direction, *, message_id: int,
    ) -> GradeResult:
        """
        Apply a 0-5 grade in the given direction, once per delivered message.
        Raises ValueError for an out-of-range grade or unknown direction
        (enforced by ExpressionService, before anything is written).

        The card write comes last because it is what makes a retry stop: if anything
        fails before it, the card is still pending and a retap grades it. The other
        order could leave a graded card with the scheduler paused and no way to resume.
        """
        check = await self.expressions.check_gradable(
            user_id, expression_id, grade, direction, message_id=message_id)
        if check == "not_found":
            return CardNotFound()
        if check == "not_pending":
            return NotPending()

        await self.review_state.record_reviewed(user_id)
        await shadow_write(
            self.review_state.record_graded(user_id, expression_id, direction),
            f"record_graded user={user_id} expression={expression_id}",
        )

        # A concurrent tap or a removal can still win between the check and this write.
        outcome = await self.expressions.grade_expression(
            user_id, expression_id, grade, direction, message_id=message_id)
        if outcome == "not_found":
            return CardNotFound()
        if outcome == "not_pending":
            return NotPending()
        return Graded()

    async def claim_first_review_tip(self, user_id: UserId) -> bool:
        """
        True exactly once, after the user's first graded review.
        Advances onboarding atomically, so concurrent grades cannot both claim it.
        """
        user = await self.users.get_user(user_id)
        if user.onboarding_step != 1:
            return False
        return await self.users.advance_onboarding(user_id, 1)


def _from_storage(expression: Expression, direction: Direction, settings: CardSettings) -> ReviewReady:
    stored = expression.last_card
    return ReviewReady(
        expression_id=expression.id,
        value=expression.value,
        direction=direction,
        card=stored.card,
        settings=stored.settings,
        quota=None,
        older_settings=stored.settings != settings,
    )
