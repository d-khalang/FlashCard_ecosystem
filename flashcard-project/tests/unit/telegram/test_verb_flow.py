"""
Tests for /verb at the Telegram entry point: query -> conjugator v2 -> overview with mood/tense
buttons, and the conjugation navigation callback (also for buttons sent before v2).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from flashcard.app.verb import VerbUseCases
from flashcard.schemas.verbs import Conjugation
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from flashcard.services.verb import ScraperConfig, VerbService
from flashcard.services.verb_practice import VerbPracticeService
from flashcard.telegram.handlers import verb
from flashcard.telegram.keyboards import get_verb_keyboard
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.telegram.ui.verb import format_verb_conjugation, format_verb_message
from tests.helpers import TEST_I18N as i18n
from tests.helpers import TEST_LANGUAGE
from tests.integration.helpers import make_cols
from tests.verb_fixtures import fake_conjugator, load

USER_ID = 999
VERB = Conjugation.model_validate(load("conjugator/conjugate-vado.json")).verb


def _deps(*, broken=False):
    cols = make_cols(users=[{"user_id": str(USER_ID)}])
    http = fake_conjugator(broken=broken)
    use_cases = VerbUseCases(
        verb_service=VerbService(http_client=http, scraper=ScraperConfig(url="http://c", port=1, api_key="k")),
        consumption_service=ConsumptionService(users=cols["users"]),
        user_service=UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults),
        expression_service=ExpressionService(expressions=cols["expression"]),
        practice_service=VerbPracticeService(practice=cols["verb_practice"]),
    )
    return SimpleNamespace(use_cases=use_cases, http=http, cols=cols,
                           logger_bot=MagicMock(send_message=AsyncMock()))


def _queries(d) -> list[str]:
    return [call["params"]["q"] for call in d.http.calls]


def _lookups(d) -> int:
    return d.cols["users"].docs[0].get("consumption", {}).get("verb_lookups", 0)


async def _run(d, text="/verb andare"):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    status = MagicMock(edit_text=AsyncMock())
    message.answer = AsyncMock(return_value=status)
    await verb.cmd_verb(message, command=Command("verb").extract_command(text),
                        verb_use_cases=d.use_cases, logger_bot=d.logger_bot, admin_id=1, i18n=i18n)
    return message, status


async def _press(d, mood="indicativo", tense="imperfetto", callback=None):
    callback = callback or MagicMock()
    callback.answer = AsyncMock()
    if not isinstance(callback.message.edit_text, AsyncMock):
        callback.message.edit_text = AsyncMock()
    data = VerbCallback(mood=mood, tense=tense, verb="andare")
    await verb.handle_conjugation(callback, data, verb_use_cases=d.use_cases, i18n=i18n)
    return callback


def _sent(message) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


class TestVerbLookup:

    async def test_found_verb_replaces_searching_message_with_overview(self):
        d = _deps()
        message, status = await _run(d)

        assert _sent(message) == [i18n.get("commands.verb.searching", verb="andare")]
        status.edit_text.assert_awaited_once_with(text=format_verb_message(VERB, "andare"),
                                                  reply_markup=get_verb_keyboard(i18n, VERB))
        assert _queries(d) == ["andare"]

    async def test_a_form_shows_its_verb(self):
        d = _deps()
        _, status = await _run(d, text="/verb vado")

        text = status.edit_text.await_args.kwargs["text"]
        assert "Requested verb: <b>vado</b>" in text and "<b>andare</b>" in text and "io → <b>vado</b>" in text

    async def test_found_verb_is_counted_and_recorded(self):
        d = _deps()
        await _run(d)

        assert _lookups(d) == 1
        assert d.cols["users"].docs[0]["verbs_recent"] == ["andare"]

    async def test_input_is_normalized(self):
        d = _deps()
        await _run(d, text="/verb   Andare  ")

        assert _queries(d) == ["andare"]

    @pytest.mark.parametrize("text", ["/verb", "/verb   "])
    async def test_no_verb_shows_instructions(self, text):
        d = _deps()
        message, _ = await _run(d, text=text)

        assert _sent(message) == [i18n.get("commands.verb.instruction")]
        assert d.http.calls == []

    @pytest.mark.parametrize("text", ["/verb io non sono mai andato", "/verb parl4re", "/verb <b>"])
    async def test_invalid_verb_is_rejected_without_lookup(self, text):
        d = _deps()
        message, _ = await _run(d, text=text)

        assert _sent(message) == [i18n.get("commands.verb.invalid")]
        assert d.http.calls == []

    @pytest.mark.parametrize("text, query", [("/verb sono andato", "sono andato"), ("/verb me ne vado", "me ne vado"),
                                             ("/verb farsi'è", "farsi'è")])
    async def test_queries_with_spaces_accents_and_apostrophes_are_looked_up(self, text, query):
        d = _deps()
        await _run(d, text=text)

        assert _queries(d) == [query]

    async def test_bot_mention_is_ignored(self):
        # Telegram adds @botname when a command is picked from the menu in groups.
        d = _deps()
        await _run(d, text="/verb@kartino_bot andare")

        assert _queries(d) == ["andare"]

    async def test_bot_mention_alone_shows_instructions(self):
        d = _deps()
        message, _ = await _run(d, text="/verb@kartino_bot")

        assert _sent(message) == [i18n.get("commands.verb.instruction")]


class TestVerbFailures:

    async def test_unknown_verb_replaces_searching_with_error_and_is_not_counted(self):
        d = _deps()
        message, status = await _run(d, text="/verb qwerty")

        assert _sent(message) == [i18n.get("commands.verb.searching", verb="qwerty")]
        status.edit_text.assert_awaited_once_with(text=i18n.get("commands.verb.api_error"), reply_markup=None)
        assert _lookups(d) == 0

    async def test_lookup_error_notifies_admin_and_replaces_searching_with_error(self):
        d = _deps(broken=True)
        message, status = await _run(d)

        status.edit_text.assert_awaited_once_with(text=i18n.get("commands.verb.api_error"), reply_markup=None)
        d.logger_bot.send_message.assert_awaited()
        assert _lookups(d) == 0


class TestConjugationButtons:

    async def test_button_shows_the_tense_and_keeps_the_keyboard(self):
        d = _deps()
        callback = await _press(d)

        callback.message.edit_text.assert_awaited_once_with(
            text=format_verb_conjugation(VERB, "indicativo", "imperfetto"),
            reply_markup=callback.message.reply_markup)
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.verb.updated"), show_alert=False)
        assert _queries(d) == ["andare"] and _lookups(d) == 0

    @pytest.mark.parametrize("mood, tense, shown", [
        ("tempi composti", "passato prossimo", ("indicativo", "passato_prossimo")),
        ("indicativo", "passato remoto", ("indicativo", "passato_remoto")),
        ("indicativo", "futuro_semplice", ("indicativo", "futuro_semplice")),
    ])
    async def test_buttons_sent_before_v2_still_work(self, mood, tense, shown):
        d = _deps()
        callback = await _press(d, mood=mood, tense=tense)

        assert callback.message.edit_text.await_args.kwargs["text"] == format_verb_conjugation(VERB, *shown)

    async def test_missing_verb_alerts(self):
        d = _deps()
        callback = MagicMock(answer=AsyncMock())
        callback.message.edit_text = AsyncMock()
        await verb.handle_conjugation(callback, VerbCallback(mood="indicativo", tense="presente", verb="qwerty"),
                                      verb_use_cases=d.use_cases, i18n=i18n)

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
