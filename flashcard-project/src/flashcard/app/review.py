"""
Review use cases: pick the next card, generate it, record its delivery and grade it.

Callers own presentation and delivery: they format the card, send it however
they deliver messages, then report the delivered message back via mark_sent.

Each delivered fresh card is stored on its expression (one card, overwritten).
When generation fails, or the user is over quota, that stored card is sent
instead, free of quota.
"""
from dataclasses import dataclass
from typing import Optional, Union

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


PrepareResult = Union[ReviewReady, NoCandidate, QuotaExceeded]


class CardGenerationFailed(RuntimeError):
    """The LLM answered but could not make a card, and none is stored."""


@dataclass(frozen=True)
class Graded:
    pass


@dataclass(frozen=True)
class CardNotFound:
    pass


GradeResult = Union[Graded, CardNotFound]


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

    async def prepare_next(self, user_id: UserId, user: Optional[UserDB] = None) -> PrepareResult:
        """
        Pick the highest-priority card and generate its content.
        Pass `user` when already loaded; otherwise it is fetched.
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

        try:
            card = await generate_card(self.llm, expression.value, settings)
        except Exception:
            if expression.last_card is None:
                raise
            logger.warning("Card generation failed for expression %s; sending its stored card",
                           expression.id, exc_info=True)
            return _from_storage(expression, direction, settings)

        if not card.success:
            if expression.last_card is None:
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

    async def grade(self, user_id: UserId, expression_id: str, grade: int, direction: Direction) -> GradeResult:
        """
        Apply a 0-5 grade in the given direction.
        Raises ValueError for an out-of-range grade or unknown direction
        (enforced by ExpressionService.grade_expression, before anything is written).
        """
        if not await self.expressions.grade_expression(user_id, expression_id, grade, direction):
            return CardNotFound()
        await self.review_state.record_reviewed(user_id)
        await shadow_write(
            self.review_state.record_graded(user_id, expression_id, direction),
            f"record_graded user={user_id} expression={expression_id}",
        )
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
