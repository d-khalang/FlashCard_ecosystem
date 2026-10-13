"""
Tests for /import at the Telegram entry point: text -> LLM-parsed list -> validated -> bulk saved.

The command text is parsed with aiogram's own Command filter, as in production.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.filters import Command

from flashcard.app.collection import MAX_IMPORT_CHARS, CollectionUseCases
from flashcard.schemas.import_model import ImportResponse
from flashcard.schemas.user import UserDB, UserTier
from flashcard.services.i18n import i18n
from flashcard.services.language_validation import LanguageValidationResult
from flashcard.telegram.handlers import collection


USER_ID = 333


def _deps(*, parsed=None, inserted=None, validation=None, can_generate=True):
    user_service = MagicMock()
    user_service.get_user = AsyncMock(return_value=UserDB(user_id=str(USER_ID), tier=UserTier.normal))
    user_service.can_generate_card = MagicMock(return_value=can_generate)
    user_service.card_limit = MagicMock(return_value=10)

    consumption_service = MagicMock()
    consumption_service.increment = AsyncMock()

    llm_service = MagicMock()
    llm_service.parse_import_list = AsyncMock(
        return_value=parsed or ImportResponse(success=True, import_list=["andare", "fare"]))

    expression_service = MagicMock()
    # Default: no duplicates, so every item passed in is reported as inserted.
    expression_service.add_expressions_bulk = (
        AsyncMock(side_effect=lambda user_id, items: list(items)) if inserted is None
        else AsyncMock(return_value=inserted))

    validator = None
    if validation is not None:
        validator = MagicMock()
        validator.validate_import_items = AsyncMock(return_value=validation)

    return SimpleNamespace(llm_service=llm_service, expression_service=expression_service, validator=validator,
                           user_service=user_service, consumption_service=consumption_service)


def _use_cases(d) -> CollectionUseCases:
    return CollectionUseCases(expression_service=d.expression_service, user_service=d.user_service,
                              consumption_service=d.consumption_service, llm_service=d.llm_service,
                              language_validator=d.validator)


async def _run(d, text="/import andare, fare", message=None):
    message = message or _message(text)
    await collection.cmd_import(message, command=Command("import").extract_command(text),
                                collection_use_cases=_use_cases(d))
    return message


def _message(text):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    message.answer = AsyncMock()
    return message


def _answered(message) -> str:
    message.answer.assert_awaited_once()
    return message.answer.await_args.args[0]


class TestImportInput:

    @pytest.mark.parametrize("text", ["/import", "/import   ", "/import\n\n", "/import@kartino_bot"])
    async def test_no_arguments_shows_usage_guide(self, text):
        d = _deps()
        message = await _run(d, text=text)

        assert _answered(message) == i18n.get("commands.import.usage_guide")
        d.llm_service.parse_import_list.assert_not_awaited()

    async def test_text_after_command_is_parsed(self):
        d = _deps()
        await _run(d, text="/import\nandare a casa\nfare colazione")

        d.llm_service.parse_import_list.assert_awaited_once_with("andare a casa\nfare colazione")

    async def test_bot_mention_is_not_sent_to_the_llm(self):
        d = _deps()
        await _run(d, text="/import@kartino_bot andare")

        d.llm_service.parse_import_list.assert_awaited_once_with("andare")

    async def test_input_at_the_limit_is_parsed(self):
        d = _deps()
        await _run(d, text="/import " + "a" * MAX_IMPORT_CHARS)

        d.llm_service.parse_import_list.assert_awaited_once()

    async def test_input_over_the_limit_is_rejected_before_the_llm(self):
        d = _deps()
        message = await _run(d, text="/import " + "a" * (MAX_IMPORT_CHARS + 1))

        assert _answered(message) == i18n.get("commands.import.too_long", limit=MAX_IMPORT_CHARS)
        d.llm_service.parse_import_list.assert_not_awaited()

    async def test_quota_exceeded_shows_limit_and_skips_llm(self):
        d = _deps(can_generate=False)
        message = await _run(d)

        assert _answered(message) == i18n.get(
            "messages.errors.quota_exceeded", type="card", tier="normal", limit=10)
        d.llm_service.parse_import_list.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_import_counts_one_card_generation(self):
        d = _deps()
        await _run(d)

        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=False)


class TestImportParsing:

    async def test_parse_failure_shows_llm_log(self):
        d = _deps(parsed=ImportResponse(success=False, import_list=[], log="not a list"))
        message = await _run(d)

        assert _answered(message) == i18n.get("commands.import.import_failed", log_msg="not a list")
        d.expression_service.add_expressions_bulk.assert_not_awaited()

    async def test_parse_failure_without_log_says_unknown_error(self):
        d = _deps(parsed=ImportResponse(success=False, import_list=[], log=None))
        message = await _run(d)

        assert _answered(message) == i18n.get("commands.import.import_failed", log_msg="Unknown error.")

    async def test_empty_list_says_no_items_found(self):
        d = _deps(parsed=ImportResponse(success=True, import_list=[]))
        message = await _run(d)

        assert _answered(message) == i18n.get("commands.import.no_items_found")
        d.expression_service.add_expressions_bulk.assert_not_awaited()

    async def test_llm_failure_propagates_to_global_error_handler(self):
        d = _deps()
        d.llm_service.parse_import_list.side_effect = RuntimeError("provider down")
        message = _message("/import andare")

        with pytest.raises(RuntimeError):
            await _run(d, text="/import andare", message=message)
        message.answer.assert_not_awaited()
        d.expression_service.add_expressions_bulk.assert_not_awaited()


class TestImportValidation:

    async def test_without_validator_saves_parsed_list(self):
        d = _deps()
        await _run(d)

        d.expression_service.add_expressions_bulk.assert_awaited_once_with(USER_ID, ["andare", "fare"])

    async def test_validator_normalized_items_are_saved(self):
        d = _deps(validation=LanguageValidationResult(is_valid=True, normalized_items=["andare"]))
        message = await _run(d)

        d.validator.validate_import_items.assert_awaited_once_with(["andare", "fare"])
        d.expression_service.add_expressions_bulk.assert_awaited_once_with(USER_ID, ["andare"])
        assert _answered(message) == i18n.get("commands.import.success", count=1, items_str="andare")

    async def test_language_rejection_says_invalid_language(self):
        d = _deps(validation=LanguageValidationResult(is_valid=False, reason="unsupported_characters"))
        message = await _run(d)

        assert _answered(message) == i18n.get("messages.errors.invalid_learning_language_input")
        d.expression_service.add_expressions_bulk.assert_not_awaited()

    async def test_valid_but_empty_validation_says_no_items_found(self):
        d = _deps(validation=LanguageValidationResult(is_valid=True, normalized_items=[]))
        message = await _run(d)

        assert _answered(message) == i18n.get("commands.import.no_items_found")
        d.expression_service.add_expressions_bulk.assert_not_awaited()


class TestImportSave:

    async def test_inserted_items_are_listed(self):
        d = _deps(inserted=["andare", "fare"])
        message = await _run(d)

        assert _answered(message) == i18n.get("commands.import.success", count=2, items_str="andare\nfare")

    async def test_all_duplicates_says_nothing_added(self):
        d = _deps(inserted=[])
        message = await _run(d)

        assert _answered(message) == i18n.get("commands.import.all_duplicates")
