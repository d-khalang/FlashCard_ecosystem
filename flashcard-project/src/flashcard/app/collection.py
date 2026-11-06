"""
Collection use cases: import expressions in bulk, list, search and remove saved ones.

Callers own presentation and command parsing: they extract the text to import
and turn results into messages.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Union, get_args

from flashcard.app.creation import TooMany
from flashcard.app.quota import QuotaExceeded, QuotaPolicy
from flashcard.app.review import GenerationGate, GenerationHeld, Throttled
from flashcard.app.shadow import shadow_write
from flashcard.schemas.expression import Expression, ExpressionCard
from flashcard.schemas.user import UserId
from flashcard.services.expression import ExpressionService, InvalidCursor
from flashcard.services.language_validation import LanguageValidityChecker
from flashcard.services.llm.llm import LLMService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

# Bounds LLM cost per import; roughly 50-100 short expressions.
MAX_IMPORT_CHARS = 1000

MIN_SEARCH_CHARS = 2
MAX_SEARCH_CHARS = 150
MAX_SEARCH_RESULTS = 50
MAX_PAGE_SIZE = 50

ListOrder = Literal["alphabetical", "created"]


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


ImportResult = Union[Imported, AllDuplicates, ParseFailed, NothingFound, InvalidLanguage, TooLong, QuotaExceeded,
                     TooMany, Throttled, GenerationHeld]


@dataclass(frozen=True)
class SavedItem:
    id: str
    value: str


@dataclass(frozen=True)
class Matches:
    items: list[SavedItem]


@dataclass(frozen=True)
class QueryTooShort:
    pass


@dataclass(frozen=True)
class QueryTooLong:
    pass


SearchResult = Union[Matches, QueryTooShort, QueryTooLong]


@dataclass(frozen=True)
class Removed:
    pass


@dataclass(frozen=True)
class NotFound:
    """No active card with this id belongs to the user (also for malformed ids)."""
    pass


RemoveResult = Union[Removed, NotFound]


@dataclass(frozen=True)
class CollectionItem:
    id: str
    value: str
    # Both directions together.
    reps: int
    lapses: int
    created_at: Optional[datetime]


@dataclass(frozen=True)
class ItemPage:
    """Newest first; `next_cursor` continues after the last item, None on the last page."""
    items: list[CollectionItem]
    next_cursor: Optional[str]


@dataclass(frozen=True)
class BadCursor:
    pass


PageResult = Union[ItemPage, QueryTooShort, QueryTooLong, BadCursor]


@dataclass(frozen=True)
class ItemDetail:
    item: CollectionItem
    # The latest card made for it; None for a word never reviewed.
    card: Optional[ExpressionCard]
    generated_at: Optional[datetime]


class CollectionUseCases:
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

    async def import_items(
        self, user_id: UserId, text: str, *, max_words: Optional[int] = None,
        before_generation: Optional[GenerationGate] = None,
    ) -> ImportResult:
        """
        Parse a free-form list with the LLM, validate the items and save the new ones.
        `max_words` (Mini App): refuse when the collection is full, or the import would exceed it.
        `before_generation` is asked right before the LLM call; a refusal is the result.
        """
        text = text.strip()
        if not text:
            return NothingFound()
        if len(text) > MAX_IMPORT_CHARS:
            return TooLong(limit=MAX_IMPORT_CHARS)

        # An import that saves something costs one card generation (CARD_CREDITS); the length
        # limit bounds its size. Imports that save nothing are free.
        user = await self.users.get_user(user_id)
        quota = self.quota.check(user, "cards")
        if isinstance(quota, QuotaExceeded):
            return quota

        saved = 0
        if max_words is not None:
            saved = (await self.expressions.count_words(user_id)).total
            if saved >= max_words:
                return TooMany(limit=max_words)
        if before_generation is not None:
            refused = before_generation()
            if refused is not None:
                return refused

        parsed = await self.llm.parse_import_list(text)
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

        if max_words is not None and saved + len(items) > max_words:
            return TooMany(limit=max_words)
        inserted = await self.expressions.add_expressions_bulk(user_id, items)
        if not inserted:
            return AllDuplicates()
        await self.quota.record(user_id, "cards", quota)
        # An active user should not be left without scheduled reviews.
        await self.review_state.clear_pending(user_id)
        return Imported(items=list(inserted))

    async def list_items(self, user_id: UserId, order: ListOrder = "alphabetical") -> list[str]:
        """All saved values: alphabetical (case-insensitive) or oldest first."""
        if order not in get_args(ListOrder):
            raise ValueError(f"Unknown list order: {order!r}")
        values = await self.expressions.get_all_expressions(user_id)  # unique, oldest first
        return sorted(values, key=str.lower) if order == "alphabetical" else values

    async def search(self, user_id: UserId, query: str) -> SearchResult:
        """Saved cards whose value contains the query, case-insensitively."""
        query = query.strip()
        if len(query) < MIN_SEARCH_CHARS:
            return QueryTooShort()
        if len(query) > MAX_SEARCH_CHARS:
            logger.warning("Skipping search for user %s: query exceeds %s characters.", user_id, MAX_SEARCH_CHARS)
            return QueryTooLong()

        expressions = await self.expressions.search_expressions(user_id, query, limit=MAX_SEARCH_RESULTS)
        return Matches(items=[SavedItem(id=e.id, value=e.value) for e in expressions])

    async def list_page(
        self, user_id: UserId, *, limit: int = MAX_PAGE_SIZE, cursor: Optional[str] = None,
        query: Optional[str] = None,
    ) -> PageResult:
        """
        Saved cards newest first, `limit` (at most 50) at a time. A `query` of 2+ characters
        searches instead, without paging.
        """
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        if query is not None:
            query = query.strip()
            if len(query) < MIN_SEARCH_CHARS:
                return QueryTooShort()
            if len(query) > MAX_SEARCH_CHARS:
                return QueryTooLong()
        try:
            page = await self.expressions.list_page(user_id, limit=limit, cursor=cursor, query=query)
        except InvalidCursor:
            return BadCursor()
        return ItemPage(items=[_item(e) for e in page.items], next_cursor=page.next_cursor)

    async def detail(self, user_id: UserId, expression_id: str) -> Union[ItemDetail, NotFound]:
        """One saved card with the latest card made for it (also NotFound for malformed ids)."""
        expression = await self.expressions.get_expression(user_id, expression_id)
        if expression is None:
            return NotFound()
        stored = expression.last_card
        return ItemDetail(
            item=_item(expression),
            card=stored.card if stored is not None else None,
            generated_at=stored.generated_at if stored is not None else None,
        )

    async def remove(self, user_id: UserId, expression_id: str) -> RemoveResult:
        removed = await self.expressions.remove_expression(user_id, expression_id)
        if not removed:
            return NotFound()
        # The removed card may be the unanswered one, which would pause the scheduler forever.
        await self.review_state.clear_pending(user_id)
        await shadow_write(
            self.review_state.record_removed(user_id, expression_id),
            f"record_removed user={user_id} expression={expression_id}",
        )
        return Removed()


def _item(expression: Expression) -> CollectionItem:
    reverse = expression.reverse_stats
    return CollectionItem(
        id=expression.id,
        value=expression.value,
        reps=expression.reps + (reverse.reps if reverse else 0),
        lapses=expression.lapses + (reverse.lapses if reverse else 0),
        created_at=expression.created_at,
    )
