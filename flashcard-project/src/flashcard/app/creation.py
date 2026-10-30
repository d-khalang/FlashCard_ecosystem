"""
Creation use cases: turn user text into a card, and save expressions.

Callers own presentation: they render the card, choose buttons and wording.
"""
from dataclasses import dataclass, field
from typing import Optional, Union

from flashcard.app.cards import FallbackNotifier, card_settings, generate_card
from flashcard.app.quota import QuotaExceeded, QuotaPolicy
from flashcard.schemas.user import UserId
from flashcard.schemas.expression import ExpressionCard
from flashcard.services.expression import ExpressionService
from flashcard.services.language_validation import LanguageValidityChecker
from flashcard.services.llm.llm import LLMService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService


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
        quota: QuotaPolicy,
        llm_service: LLMService,
        review_state: ReviewStateStore,
        language_validator: Optional[LanguageValidityChecker] = None,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.quota = quota
        self.llm = llm_service
        self.review_state = review_state
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

        quota = self.quota.check(user, "cards")
        if isinstance(quota, QuotaExceeded):
            return quota

        card = await generate_card(self.llm, text, card_settings(user), on_fallback=on_fallback)

        if not card.success:
            return Unclear(card=card)

        await self.quota.record(user_id, "cards", quota)
        return CardReady(card=card)

    async def save(self, user_id: UserId, norm: str) -> SaveResult:
        """Add an expression to the user's collection unless it already exists."""
        saved = await self.expressions.add_expression(user_id, norm)
        if not saved:
            return AlreadySaved()
        # An active user should not be left without scheduled reviews.
        await self.review_state.clear_pending(user_id)
        return Saved()

    async def claim_first_save_tip(self, user_id: UserId) -> bool:
        """
        True exactly once, after the user's first save.
        Advances onboarding atomically, so concurrent saves cannot both claim it.
        """
        user = await self.users.get_user(user_id)
        if user.onboarding_step != 0:
            return False
        return await self.users.advance_onboarding(user_id, 0)
