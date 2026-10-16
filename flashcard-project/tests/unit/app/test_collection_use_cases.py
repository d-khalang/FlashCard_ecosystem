"""
Unit tests for CollectionUseCases: import, list, search and remove, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bson import ObjectId

from flashcard.app.collection import (
    MAX_IMPORT_CHARS, MAX_SEARCH_CHARS, MAX_SEARCH_RESULTS, AllDuplicates, CollectionUseCases, Imported,
    InvalidLanguage, Matches, NotFound, NothingFound, ParseFailed, QueryTooLong, QueryTooShort, Removed,
    SavedItem, TooLong,
)
from flashcard.app.quota import QuotaExceeded
from flashcard.schemas.import_model import ImportResponse
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier
from flashcard.services.language_validation import LanguageValidationResult


def _user(**overrides) -> UserDB:
    fields = {"user_id": "333", "tier": UserTier.normal}
    fields.update(overrides)
    return UserDB(**fields)


def _use_cases(*, parsed=None, inserted=None, validation=None, user=None, can_generate=True, card_limit=10):
    expressions = MagicMock()
    # Default: no duplicates, so every item passed in is reported as inserted.
    expressions.add_expressions_bulk = (
        AsyncMock(side_effect=lambda user_id, items: list(items)) if inserted is None
        else AsyncMock(return_value=inserted))

    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or _user())
    users.can_generate_card = MagicMock(return_value=can_generate)
    users.card_limit = MagicMock(return_value=card_limit)

    consumption = MagicMock()
    consumption.increment = AsyncMock()

    llm = MagicMock()
    llm.parse_import_list = AsyncMock(
        return_value=parsed or ImportResponse(success=True, import_list=["andare", "fare"]))

    validator = None
    if validation is not None:
        validator = MagicMock()
        validator.validate_import_items = AsyncMock(return_value=validation)

    use_cases = CollectionUseCases(review_state=AsyncMock(), expression_service=expressions, user_service=users,
                                   consumption_service=consumption, llm_service=llm,
                                   language_validator=validator)
    return use_cases, expressions, users, consumption, llm


class TestImportItems:

    async def test_new_items_are_saved_and_returned(self):
        use_cases, expressions, _, _, llm = _use_cases()

        assert await use_cases.import_items(333, "andare, fare") == Imported(items=["andare", "fare"])
        llm.parse_import_list.assert_awaited_once_with("andare, fare")
        expressions.add_expressions_bulk.assert_awaited_once_with(333, ["andare", "fare"])
        use_cases.review_state.clear_pending.assert_awaited_once_with(333)

    async def test_only_newly_inserted_items_are_returned(self):
        use_cases, *_ = _use_cases(inserted=["fare"])

        assert await use_cases.import_items(333, "andare, fare") == Imported(items=["fare"])

    async def test_all_duplicates(self):
        use_cases, *_ = _use_cases(inserted=[])

        assert await use_cases.import_items(333, "andare") == AllDuplicates()
        use_cases.review_state.clear_pending.assert_not_awaited()

    @pytest.mark.parametrize("log", ["not a list", None])
    async def test_parse_failure_keeps_llm_log(self, log):
        use_cases, expressions, *_ = _use_cases(parsed=ImportResponse(success=False, import_list=[], log=log))

        assert await use_cases.import_items(333, "???") == ParseFailed(log=log)
        expressions.add_expressions_bulk.assert_not_awaited()

    async def test_empty_parse_is_nothing_found(self):
        use_cases, expressions, *_ = _use_cases(parsed=ImportResponse(success=True, import_list=[]))

        assert await use_cases.import_items(333, "...") == NothingFound()
        expressions.add_expressions_bulk.assert_not_awaited()

    async def test_validator_normalized_items_are_saved(self):
        use_cases, expressions, *_ = _use_cases(
            validation=LanguageValidationResult(is_valid=True, normalized_items=["andare"]))

        assert await use_cases.import_items(333, "andare, fare") == Imported(items=["andare"])
        expressions.add_expressions_bulk.assert_awaited_once_with(333, ["andare"])

    async def test_language_rejection_is_invalid_language(self):
        use_cases, expressions, *_ = _use_cases(
            validation=LanguageValidationResult(is_valid=False, reason="unsupported_characters"))

        assert await use_cases.import_items(333, "hello") == InvalidLanguage()
        expressions.add_expressions_bulk.assert_not_awaited()

    async def test_valid_but_empty_validation_is_nothing_found(self):
        use_cases, expressions, *_ = _use_cases(
            validation=LanguageValidationResult(is_valid=True, normalized_items=[]))

        assert await use_cases.import_items(333, "...") == NothingFound()
        expressions.add_expressions_bulk.assert_not_awaited()

    @pytest.mark.parametrize("text", ["", "   ", "\n\t "])
    async def test_blank_text_is_nothing_found_without_llm(self, text):
        use_cases, _, _, _, llm = _use_cases()

        assert await use_cases.import_items(333, text) == NothingFound()
        llm.parse_import_list.assert_not_awaited()

    async def test_surrounding_whitespace_is_stripped_before_llm(self):
        use_cases, _, _, _, llm = _use_cases()

        await use_cases.import_items(333, "  andare, fare \n")
        llm.parse_import_list.assert_awaited_once_with("andare, fare")

    async def test_text_at_limit_is_parsed(self):
        use_cases, _, _, _, llm = _use_cases()

        await use_cases.import_items(333, "a" * MAX_IMPORT_CHARS)
        llm.parse_import_list.assert_awaited_once()

    async def test_text_over_limit_is_too_long_without_llm(self):
        use_cases, _, _, _, llm = _use_cases()

        assert await use_cases.import_items(333, "a" * (MAX_IMPORT_CHARS + 1)) == TooLong(limit=MAX_IMPORT_CHARS)
        llm.parse_import_list.assert_not_awaited()

    async def test_limit_counts_text_after_stripping(self):
        use_cases, _, _, _, llm = _use_cases()

        await use_cases.import_items(333, "  " + "a" * MAX_IMPORT_CHARS + "  ")
        llm.parse_import_list.assert_awaited_once()

    async def test_llm_failure_propagates_and_saves_nothing(self):
        use_cases, expressions, _, _, llm = _use_cases()
        llm.parse_import_list.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            await use_cases.import_items(333, "andare")
        expressions.add_expressions_bulk.assert_not_awaited()


class TestImportQuota:
    """One import costs one card generation, counted once the LLM has answered."""

    async def test_successful_import_counts_one_generation(self):
        use_cases, _, users, consumption, _ = _use_cases()

        await use_cases.import_items(333, "andare, fare")

        users.can_generate_card.assert_called_once_with(users.get_user.return_value, uses_own_key=False)
        consumption.increment.assert_awaited_once_with(333, "cards_generated", uses_own_key=False)

    @pytest.mark.parametrize("kwargs", [
        {"parsed": ImportResponse(success=False, import_list=[], log="not a list")},
        {"parsed": ImportResponse(success=True, import_list=[])},
        {"validation": LanguageValidationResult(is_valid=False)},
        {"inserted": []},
    ], ids=["parse_failed", "nothing_found", "invalid_language", "all_duplicates"])
    async def test_answered_llm_call_is_counted_whatever_the_outcome(self, kwargs):
        use_cases, _, _, consumption, _ = _use_cases(**kwargs)

        await use_cases.import_items(333, "andare, fare")
        consumption.increment.assert_awaited_once()

    async def test_quota_exceeded_skips_llm_and_counts_nothing(self):
        user = _user(tier=UserTier.normal)
        use_cases, expressions, users, consumption, llm = _use_cases(user=user, can_generate=False, card_limit=10)

        assert await use_cases.import_items(333, "andare") == QuotaExceeded(tier="normal", limit=10)
        users.card_limit.assert_called_once_with(user)
        llm.parse_import_list.assert_not_awaited()
        consumption.increment.assert_not_awaited()
        expressions.add_expressions_bulk.assert_not_awaited()

    async def test_own_api_key_is_used_for_quota_and_usage(self):
        user = _user(api_config=UserAPIConfig(api_key="test"))
        use_cases, _, users, consumption, _ = _use_cases(user=user)

        await use_cases.import_items(333, "andare")
        users.can_generate_card.assert_called_once_with(user, uses_own_key=True)
        consumption.increment.assert_awaited_once_with(333, "cards_generated", uses_own_key=True)

    async def test_llm_error_is_not_counted(self):
        use_cases, _, _, consumption, llm = _use_cases()
        llm.parse_import_list.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            await use_cases.import_items(333, "andare")
        consumption.increment.assert_not_awaited()

    @pytest.mark.parametrize("text", ["   ", "a" * (MAX_IMPORT_CHARS + 1)], ids=["blank", "too_long"])
    async def test_rejected_input_never_touches_quota(self, text):
        use_cases, _, users, consumption, _ = _use_cases()

        await use_cases.import_items(333, text)
        users.get_user.assert_not_awaited()
        consumption.increment.assert_not_awaited()


def _saved(*, values=None, found=None, removed=True):
    expressions = MagicMock()
    expressions.get_all_expressions = AsyncMock(return_value=list(values or []))
    expressions.search_expressions = AsyncMock(return_value=list(found or []))
    expressions.remove_expression = AsyncMock(return_value=removed)
    use_cases = CollectionUseCases(review_state=AsyncMock(), expression_service=expressions, user_service=MagicMock(),
                                   consumption_service=MagicMock(), llm_service=MagicMock())
    return use_cases, expressions


class TestListItems:

    async def test_alphabetical_ignores_case(self):
        use_cases, expressions = _saved(values=["fare", "Andare", "bere"])

        assert await use_cases.list_items(333) == ["Andare", "bere", "fare"]
        expressions.get_all_expressions.assert_awaited_once_with(333)

    async def test_created_keeps_storage_order(self):
        use_cases, expressions = _saved(values=["fare", "Andare", "bere"])

        assert await use_cases.list_items(333, order="created") == ["fare", "Andare", "bere"]
        expressions.get_all_expressions.assert_awaited_once_with(333)

    async def test_unknown_order_is_rejected(self):
        use_cases, expressions = _saved()

        with pytest.raises(ValueError):
            await use_cases.list_items(333, order="newest")
        expressions.get_all_expressions.assert_not_awaited()


class TestSearch:

    @pytest.mark.parametrize("query", ["", "a", "  a  "])
    async def test_short_query_does_not_search(self, query):
        use_cases, expressions = _saved()

        assert await use_cases.search(333, query) == QueryTooShort()
        expressions.search_expressions.assert_not_awaited()

    async def test_long_query_does_not_search(self):
        use_cases, expressions = _saved()

        assert await use_cases.search(333, "a" * (MAX_SEARCH_CHARS + 1)) == QueryTooLong()
        expressions.search_expressions.assert_not_awaited()

    async def test_query_at_the_limit_is_searched(self):
        use_cases, expressions = _saved()

        assert await use_cases.search(333, "a" * MAX_SEARCH_CHARS) == Matches(items=[])
        expressions.search_expressions.assert_awaited_once()

    async def test_matches_are_typed_and_malformed_ones_skipped(self):
        good = ObjectId()
        use_cases, expressions = _saved(found=[{"value": "no id"}, {"_id": ObjectId(), "value": ""},
                                               {"_id": good, "value": "casa"}])

        assert await use_cases.search(333, " cas ") == Matches(items=[SavedItem(id=str(good), value="casa")])
        expressions.search_expressions.assert_awaited_once_with(333, "cas", limit=MAX_SEARCH_RESULTS)


class TestRemove:

    async def test_removed(self):
        use_cases, expressions = _saved(removed=True)

        assert await use_cases.remove(333, "abc") == Removed()
        expressions.remove_expression.assert_awaited_once_with(333, "abc")
        use_cases.review_state.clear_pending.assert_awaited_once_with(333)

    async def test_not_found(self):
        use_cases, _ = _saved(removed=False)

        assert await use_cases.remove(333, "abc") == NotFound()
        use_cases.review_state.clear_pending.assert_not_awaited()
        use_cases.review_state.record_removed.assert_not_awaited()

    async def test_removed_clears_the_current_review(self):
        use_cases, _ = _saved(removed=True)

        await use_cases.remove(333, "abc")

        use_cases.review_state.record_removed.assert_awaited_once_with(333, "abc")

    async def test_removed_survives_a_review_state_failure(self):
        use_cases, _ = _saved(removed=True)
        use_cases.review_state.record_removed.side_effect = RuntimeError("mongo down")

        assert await use_cases.remove(333, "abc") == Removed()
        use_cases.review_state.clear_pending.assert_awaited_once_with(333)
