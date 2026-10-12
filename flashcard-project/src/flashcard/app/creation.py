"""
Creation use cases: turn user text into a card, and save expressions.

Callers own presentation: they render the card, choose buttons and wording.
"""
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Union

from flashcard.app.quota import QuotaExceeded
from flashcard.app.types import UserId
from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.languages import get_language_flag
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.language_validation import LanguageValidityChecker
from flashcard.services.llm.llm import LLMService
from flashcard.services.user import UserService

FallbackNotifier = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class CardReady:
    card: ExpressionCard


@dataclass(frozen=True)
class Unclear:
    """The LLM could not understand the input; `card.note` says why."""
    card: ExpressionCard


@dataclass(frozen=True)
class InvalidInput:
    """The input is not in the learning language."""
    suggestions: list[str] = field(default_factory=list)


GenerateResult = Union[CardReady, Unclear, InvalidInput, QuotaExceeded]


@dataclass(frozen=True)
class Saved:
    pass


@dataclass(frozen=True)
class AlreadySaved:
    pass


SaveResult = Union[Saved, AlreadySaved]


class CreationUseCases:
    def __init__(
        self,
        expression_service: ExpressionService,
        user_service: UserService,
        consumption_service: ConsumptionService,
        llm_service: LLMService,
        language_validator: Optional[LanguageValidityChecker] = None,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.consumption = consumption_service
        self.llm = llm_service
        self.validator = language_validator

    async def generate(
        self,
        user_id: UserId,
        text: str,
        on_fallback: Optional[FallbackNotifier] = None,
    ) -> GenerateResult:
        """
        Validate the text, check quota, generate a card and count usage.
        `on_fallback` is awaited if the primary LLM provider fails over.
        """
        user = await self.users.get_user(user_id)

        if self.validator is not None:
            validation = await self.validator.validate_expression(text)
            if not validation.is_valid:
                return InvalidInput(suggestions=list(validation.suggestions))
            if validation.normalized_text:
                text = validation.normalized_text

        uses_own_key = user.api_config is not None
        if not self.users.can_generate_card(user, uses_own_key=uses_own_key):
            return QuotaExceeded(tier=user.tier.value, limit=self.users.card_limit(user))

        lang1_code = user.primary_language
        lang2_code = user.secondary_language
        card = await self.llm.generate_expression_card(
            raw=text,
            level=user.target_level,
            lang1_code=lang1_code,
            lang2_code=lang2_code,
            lang1_label=get_language_flag(lang1_code),
            lang2_label=get_language_flag(lang2_code) if lang2_code else None,
            on_fallback=on_fallback,
        )

        if not card.success:
            return Unclear(card=card)

        await self.consumption.increment(user_id, "cards_generated", uses_own_key=uses_own_key)
        return CardReady(card=card)

    async def save(self, user_id: UserId, norm: str) -> SaveResult:
        """Add an expression to the user's collection unless it already exists."""
        saved = await self.expressions.add_expression(user_id, norm)
        return Saved() if saved else AlreadySaved()

    async def claim_first_save_tip(self, user_id: UserId) -> bool:
        """
        True exactly once, after the user's first save.
        Advances onboarding atomically, so concurrent saves cannot both claim it.
        """
        user = await self.users.get_user(user_id)
        if user.onboarding_step != 0:
            return False
        return await self.users.advance_onboarding(user_id, 0)
