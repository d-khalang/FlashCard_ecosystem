"""
Characterization tests for /import: text -> LLM-parsed list -> validated -> bulk saved.

They pin current behavior at the entry point so import logic can be moved into
a use-case layer without changing what users see or what is written.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.schemas.import_model import ImportResponse
from flashcard.services.i18n import i18n
from flashcard.services.language_validation import LanguageValidationResult
from flashcard.telegram.handlers import collection


USER_ID = 333


def _deps(*, parsed=None, inserted=None, validation=None):
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

    return SimpleNamespace(llm_service=llm_service, expression_service=expression_service, validator=validator)


async def _run(d, text="/import andare, fare"):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    message.answer = AsyncMock()
    await collection.cmd_import(message, llm_service=d.llm_service, expression_service=d.expression_service,
                                language_validator=d.validator)
    return message


def _answered(message) -> str:
    message.answer.assert_awaited_once()
    return message.answer.await_args.args[0]


class TestImportInput:

    @pytest.mark.parametrize("text", ["/import", "", None])
    async def test_no_arguments_shows_usage_guide(self, text):
        d = _deps()
        message = await _run(d, text=text)

        assert _answered(message) == i18n.get("commands.import.usage_guide")
        d.llm_service.parse_import_list.assert_not_awaited()

    async def test_text_after_command_is_parsed_as_is(self):
        d = _deps()
        await _run(d, text="/import\nandare a casa\nfare colazione")

        d.llm_service.parse_import_list.assert_awaited_once_with("\nandare a casa\nfare colazione")

    async def test_whitespace_only_arguments_still_reach_the_llm(self):
        d = _deps()
        await _run(d, text="/import   ")

        d.llm_service.parse_import_list.assert_awaited_once_with("   ")

    async def test_bot_mention_is_not_stripped_from_arguments(self):
        d = _deps()
        await _run(d, text="/import@kartino_bot andare")

        d.llm_service.parse_import_list.assert_awaited_once_with("@kartino_bot andare")


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

    async def test_llm_failure_propagates_and_saves_nothing(self):
        d = _deps()
        d.llm_service.parse_import_list.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            await _run(d)
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

    @pytest.mark.parametrize("validation", [
        LanguageValidationResult(is_valid=False, reason="unsupported_characters"),
        LanguageValidationResult(is_valid=True, normalized_items=[]),
    ])
    async def test_invalid_or_empty_validation_says_no_items_found(self, validation):
        d = _deps(validation=validation)
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
