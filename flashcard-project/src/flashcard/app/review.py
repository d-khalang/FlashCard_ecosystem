"""
Review use cases: pick the next card, generate it and record its delivery.

Callers own presentation and delivery: they format the card, send it however
they deliver messages, then report the delivered message back via mark_sent.
"""
from dataclasses import dataclass
from typing import Optional, Union

from flashcard.schemas.defaults import DEFAULT_LANG_1_CODE, DEFAULT_LANG_LEVEL
from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.languages import get_language_flag
from flashcard.schemas.user import UserDB
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.services.user import UserService

UserId = Union[str, int]


@dataclass(frozen=True)
class ReviewReady:
    expression_id: str
    value: str
    direction: str
    card: ExpressionCard
    uses_own_key: bool


@dataclass(frozen=True)
class NoCandidate:
    pass


@dataclass(frozen=True)
class QuotaExceeded:
    tier: str
    limit: int


PrepareResult = Union[ReviewReady, NoCandidate, QuotaExceeded]


class ReviewUseCases:
    def __init__(
        self,
        expression_service: ExpressionService,
        user_service: UserService,
        consumption_service: ConsumptionService,
        llm_service: LLMService,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.consumption = consumption_service
        self.llm = llm_service

    async def prepare_next(self, user_id: UserId, user: Optional[UserDB] = None) -> PrepareResult:
        """
        Pick the highest-priority card and generate its content.
        Pass `user` when already loaded; otherwise it is fetched.
        """
        result = await self.expressions.get_review_candidate(user_id)
        if not result:
            return NoCandidate()

        candidate = result["doc"]
        direction = result.get("direction", "forward")

        if user is None:
            user = await self.users.get_user(user_id)

        uses_own_key = user.api_config is not None
        if not self.users.can_generate_card(user, uses_own_key=uses_own_key):
            limits = self.users._get_effective_limits(user)
            return QuotaExceeded(tier=user.tier.value, limit=limits["cards"])

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
        """Record a delivered review: pending message, last push and usage."""
        await self.expressions.update_expression_sent(ready.expression_id, message_id)
        await self.users.update_user_last_push(user_id)
        await self.consumption.increment(user_id, "cards_generated", uses_own_key=ready.uses_own_key)
