"""
Collection use cases: import expressions in bulk.

Callers own presentation and command parsing: they extract the text to import
and turn results into messages.
"""
from dataclasses import dataclass
from typing import Optional, Union

from flashcard.app.quota import QuotaExceeded
from flashcard.app.types import UserId
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.language_validation import LanguageValidityChecker
from flashcard.services.llm.llm import LLMService
from flashcard.services.user import UserService

# Bounds LLM cost per import; roughly 50-100 short expressions.
MAX_IMPORT_CHARS = 1000


@dataclass(frozen=True)
class Imported:
    """Newly saved items, in the order they were inserted."""
    items: list[str]


@dataclass(frozen=True)
class AllDuplicates:
    pass


@dataclass(frozen=True)
class ParseFailed:
    """The LLM could not read the text as a list; `log` may explain why."""
    log: Optional[str] = None


@dataclass(frozen=True)
class NothingFound:
    """No usable learning-language items in the text."""
    pass


@dataclass(frozen=True)
class InvalidLanguage:
    """The items are not in the learning language."""
    pass


@dataclass(frozen=True)
class TooLong:
    limit: int


ImportResult = Union[Imported, AllDuplicates, ParseFailed, NothingFound, InvalidLanguage, TooLong, QuotaExceeded]


class CollectionUseCases:
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

    async def import_items(self, user_id: UserId, text: str) -> ImportResult:
        """Parse a free-form list with the LLM, validate the items and save the new ones."""
        text = text.strip()
        if not text:
            return NothingFound()
        if len(text) > MAX_IMPORT_CHARS:
            return TooLong(limit=MAX_IMPORT_CHARS)

        # One import costs one card generation; the length limit bounds its size.
        user = await self.users.get_user(user_id)
        uses_own_key = user.api_config is not None
        if not self.users.can_generate_card(user, uses_own_key=uses_own_key):
            return QuotaExceeded(tier=user.tier.value, limit=self.users.card_limit(user))

        parsed = await self.llm.parse_import_list(text)
        await self.consumption.increment(user_id, "cards_generated", uses_own_key=uses_own_key)
        if not parsed.success:
            return ParseFailed(log=parsed.log)
        if not parsed.import_list:
            return NothingFound()

        items = parsed.import_list
        if self.validator is not None:
            validation = await self.validator.validate_import_items(items)
            if not validation.is_valid:
                return InvalidLanguage()
            if not validation.normalized_items:
                return NothingFound()
            items = validation.normalized_items

        inserted = await self.expressions.add_expressions_bulk(user_id, items)
        return Imported(items=list(inserted)) if inserted else AllDuplicates()
