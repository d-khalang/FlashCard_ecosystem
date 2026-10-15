"""
Review use cases: pick the next card, generate it, record its delivery and grade it.

Callers own presentation and delivery: they format the card, send it however
they deliver messages, then report the delivered message back via mark_sent.
"""
from dataclasses import dataclass
from typing import Literal, Optional, Union, get_args

from flashcard.app.quota import QuotaExceeded
from flashcard.app.shadow import shadow_write
from flashcard.app.types import UserId
from flashcard.schemas.defaults import DEFAULT_LANG_1_CODE, DEFAULT_LANG_LEVEL
from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.languages import get_language_flag
from flashcard.schemas.user import UserDB
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService

Direction = Literal["forward", "reverse"]

MIN_GRADE = 0
MAX_GRADE = 5


@dataclass(frozen=True)
class ReviewReady:
    expression_id: str
    value: str
    direction: Direction
    card: ExpressionCard
    uses_own_key: bool


@dataclass(frozen=True)
class NoCandidate:
    pass


PrepareResult = Union[ReviewReady, NoCandidate, QuotaExceeded]


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
        consumption_service: ConsumptionService,
        llm_service: LLMService,
        review_state: ReviewStateStore,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.consumption = consumption_service
        self.llm = llm_service
        self.review_state = review_state

    async def prepare_next(self, user_id: UserId, user: Optional[UserDB] = None) -> PrepareResult:
        """
        Pick the highest-priority card and generate its content.
        Pass `user` when already loaded; otherwise it is fetched.
        """
        if user is None:
            user = await self.users.get_user(user_id)

        result = await self.expressions.get_review_candidate(user_id, user.review_mode)
        if not result:
            return NoCandidate()

        candidate = result["doc"]
        direction = result.get("direction", "forward")

        uses_own_key = user.api_config is not None
        if not self.users.can_generate_card(user, uses_own_key=uses_own_key):
            return QuotaExceeded(tier=user.tier.value, limit=self.users.card_limit(user))

        card = await self.llm.generate_expression_card(
            raw=candidate["value"],
            level=user.target_level or DEFAULT_LANG_LEVEL,
            lang1_code=user.primary_language or DEFAULT_LANG_1_CODE,
            lang2_code=user.secondary_language,
            lang1_label=get_language_flag(user.primary_language),
            lang2_label=get_language_flag(user.secondary_language),
        )
        return ReviewReady(
            expression_id=str(candidate["_id"]),
            value=candidate["value"],
            direction=direction,
            card=card,
            uses_own_key=uses_own_key,
        )

    async def mark_sent(self, user_id: UserId, ready: ReviewReady, message_id: int) -> None:
        """Record a delivered review: pending message, review state and usage."""
        await self.expressions.update_expression_sent(ready.expression_id, message_id)
        await self.review_state.mark_pending(user_id)
        await self.consumption.increment(user_id, "cards_generated", uses_own_key=ready.uses_own_key)
        await shadow_write(
            self.review_state.record_sent(user_id, ready.expression_id, ready.direction, message_id),
            f"record_sent user={user_id} expression={ready.expression_id}",
        )

    async def grade(self, user_id: UserId, expression_id: str, grade: int, direction: Direction) -> GradeResult:
        """
        Apply a 0-5 grade in the given direction.
        Raises ValueError for an out-of-range grade or unknown direction.
        """
        if type(grade) is not int or not MIN_GRADE <= grade <= MAX_GRADE:
            raise ValueError(f"grade must be an integer {MIN_GRADE}-{MAX_GRADE}, got {grade!r}")
        if direction not in get_args(Direction):
            raise ValueError(f"direction must be one of {get_args(Direction)}, got {direction!r}")

        updated = await self.expressions.grade_expression(user_id, expression_id, grade, direction)
        if not updated:
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
