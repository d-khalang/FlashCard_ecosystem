"""
Tests for /verb at the Telegram entry point: verb -> conjugation (cache or scraper) -> overview
with mood/tense buttons, and the conjugation navigation callback.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from flashcard.app.verb import VerbUseCases
from flashcard.schemas.conjugations import ConjugationResponse
from tests.helpers import TEST_I18N as i18n
from flashcard.services.verb import VerbService
from flashcard.telegram.handlers import verb
from flashcard.telegram.keyboards import get_verb_keyboard
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.telegram.ui.verb import format_verb_conjugation, format_verb_message


USER_ID = 999
DATA = ConjugationResponse(
    queried="parlare", url="https://example.com/parlare",
    principal_forms={"infinito": "parlare", "gerundio": "parlando"}, auxiliary="avere",
    conjugations={"indicativo": {
        "presente": {"io": "parlo", "tu": "parli", "lui, lei, Lei, egli": "parla",
                     "noi": "parliamo", "voi": "parlate", "loro, Loro, essi": "parlano"},
        "imperfetto": {"io": "parlavo", "tu": "parlavi", "lui, lei, Lei, egli": "parlava",
                       "noi": "parlavamo", "voi": "parlavate", "loro, Loro, essi": "parlavano"},
    }},
)


def _deps(*, data=DATA):
    # Real parsing and validation; only the lookup (DB cache, then scraper) is faked.
    verb_service = VerbService(conjugations=MagicMock())
    verb_service.get_verb_data = (
        AsyncMock(side_effect=data) if isinstance(data, Exception) else AsyncMock(return_value=data))

    consumption_service = MagicMock()
    consumption_service.increment = AsyncMock()

    return SimpleNamespace(verb_service=verb_service, consumption_service=consumption_service,
                           logger_bot=MagicMock(send_message=AsyncMock()))


def _use_cases(d) -> VerbUseCases:
    return VerbUseCases(verb_service=d.verb_service, consumption_service=d.consumption_service)


async def _run(d, text="/verb parlare"):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    status = MagicMock(edit_text=AsyncMock())
    message.answer = AsyncMock(return_value=status)
    await verb.cmd_verb(message, command=Command("verb").extract_command(text),
                        verb_use_cases=_use_cases(d), logger_bot=d.logger_bot, admin_id=1, i18n=i18n)
    return message, status


async def _press(d, mood="indicativo", tense="imperfetto", callback=None):
    callback = callback or MagicMock()
    callback.answer = AsyncMock()
    if not isinstance(callback.message.edit_text, AsyncMock):
        callback.message.edit_text = AsyncMock()
    data = VerbCallback(mood=mood, tense=tense, verb="parlare")
    await verb.handle_conjugation(callback, data, verb_use_cases=_use_cases(d), i18n=i18n)
    return callback


def _sent(message) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


class TestVerbLookup:

    async def test_found_verb_replaces_searching_message_with_overview(self):
        d = _deps()
        message, status = await _run(d)

        assert _sent(message) == [i18n.get("commands.verb.searching", verb="parlare")]
        status.edit_text.assert_awaited_once_with(text=format_verb_message(DATA), reply_markup=get_verb_keyboard(i18n, DATA))
        d.verb_service.get_verb_data.assert_awaited_once_with("parlare")

    async def test_found_verb_is_counted(self):
        d = _deps()
        await _run(d)

        d.consumption_service.increment.assert_awaited_once_with(USER_ID, "verb_lookups")

    async def test_input_is_stripped(self):
        d = _deps()
        await _run(d, text="/verb   parlare  ")

        d.verb_service.get_verb_data.assert_awaited_once_with("parlare")

    @pytest.mark.parametrize("text", ["/verb", "/verb   "])
    async def test_no_verb_shows_instructions(self, text):
        d = _deps()
        message, _ = await _run(d, text=text)

        assert _sent(message) == [i18n.get("commands.verb.instruction")]
        d.verb_service.get_verb_data.assert_not_awaited()

    @pytest.mark.parametrize("text", ["/verb andare a casa", "/verb parl4re", "/verb <b>"])
    async def test_invalid_verb_is_rejected_without_lookup(self, text):
        d = _deps()
        message, _ = await _run(d, text=text)

        assert _sent(message) == [i18n.get("commands.verb.invalid")]
        d.verb_service.get_verb_data.assert_not_awaited()

    async def test_accented_and_apostrophe_verbs_are_valid(self):
        d = _deps()
        await _run(d, text="/verb farsi'è")

        d.verb_service.get_verb_data.assert_awaited_once_with("farsi'è")

    async def test_bot_mention_is_ignored(self):
        # Telegram adds @botname when a command is picked from the menu in groups.
        d = _deps()
        await _run(d, text="/verb@kartino_bot parlare")

        d.verb_service.get_verb_data.assert_awaited_once_with("parlare")

    async def test_bot_mention_alone_shows_instructions(self):
        d = _deps()
        message, _ = await _run(d, text="/verb@kartino_bot")

        assert _sent(message) == [i18n.get("commands.verb.instruction")]


class TestVerbFailures:

    async def test_unknown_verb_replaces_searching_with_error_and_is_not_counted(self):
        d = _deps(data=None)
        message, status = await _run(d)

        assert _sent(message) == [i18n.get("commands.verb.searching", verb="parlare")]
        status.edit_text.assert_awaited_once_with(text=i18n.get("commands.verb.api_error"), reply_markup=None)
        d.consumption_service.increment.assert_not_awaited()

    async def test_lookup_error_notifies_admin_and_replaces_searching_with_error(self):
        d = _deps(data=RuntimeError("scraper down"))
        message, status = await _run(d)

        assert _sent(message) == [i18n.get("commands.verb.searching", verb="parlare")]
        status.edit_text.assert_awaited_once_with(text=i18n.get("commands.verb.api_error"), reply_markup=None)
        d.logger_bot.send_message.assert_awaited()
        d.consumption_service.increment.assert_not_awaited()


class TestConjugationButtons:

    async def test_button_shows_the_tense_and_keeps_the_keyboard(self):
        d = _deps()
        callback = await _press(d)

        callback.message.edit_text.assert_awaited_once_with(
            text=format_verb_conjugation(DATA, "indicativo", "imperfetto"),
            reply_markup=callback.message.reply_markup)
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.verb.updated"), show_alert=False)
        d.verb_service.get_verb_data.assert_awaited_once_with("parlare")

    async def test_missing_verb_data_alerts(self):
        d = _deps(data=None)
        callback = await _press(d)

        callback.message.edit_text.assert_not_awaited()
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.verb.not_found"), show_alert=True)

    async def test_same_button_twice_still_answers_the_tap(self):
        # Telegram rejects an edit that changes nothing; the tap must still be answered.
        d = _deps()
        callback = MagicMock()
        callback.message.edit_text = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="message is not modified"))
        await _press(d, callback=callback)

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.verb.updated"), show_alert=False)

    async def test_header_button_only_stops_the_spinner(self):
        callback = MagicMock(answer=AsyncMock())
        await verb.handle_header_button(callback)

        callback.answer.assert_awaited_once_with("", show_alert=False)
