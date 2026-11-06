"""The bot's listen buttons, with Telegram and the use cases faked."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile

from flashcard.app.audio import Clip, ListenablePart, PartMissing, SpeechFailed
from flashcard.app.quota import QuotaExceeded
from flashcard.telegram.handlers import audio as handler
from flashcard.telegram.ui.factories.audio_callback import AUDIO_MENU, AudioCallback
from tests.helpers import TEST_I18N

EXPRESSION_ID = "0" * 24


@pytest.fixture(autouse=True)
def fresh_taps(monkeypatch):
    monkeypatch.setattr(handler, "_recent", handler._RecentTaps())


def _callback():
    return SimpleNamespace(
        from_user=SimpleNamespace(id=7),
        message=SimpleNamespace(chat=SimpleNamespace(id=7), message_id=99),
        answer=AsyncMock(),
    )


def _bot(voice_file_id="voice-file"):
    return SimpleNamespace(
        send_voice=AsyncMock(return_value=SimpleNamespace(voice=SimpleNamespace(file_id=voice_file_id))),
        send_audio=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )


def _uses(result=None, parts=None):
    return SimpleNamespace(
        clip=AsyncMock(return_value=result or Clip(audio=b"mp3")),
        parts=AsyncMock(return_value=parts),
        remember_telegram_file=AsyncMock(),
    )


def _data(part):
    return AudioCallback(expression_id=EXPRESSION_ID, part=part, direction="fwd")


async def _tap(callback, part, uses, bot):
    await handler.handle_audio(callback, _data(part), uses, bot, TEST_I18N)


class TestMenu:

    async def test_opens_the_parts_of_the_card_and_keeps_the_grades(self):
        bot, uses = _bot(), _uses(parts=[ListenablePart("word"), ListenablePart("translation_0", "🇮🇷 FA")])

        await _tap(_callback(), AUDIO_MENU, uses, bot)

        kwargs = bot.edit_message_reply_markup.await_args.kwargs
        assert (kwargs["chat_id"], kwargs["message_id"]) == (7, 99)
        keyboard = kwargs["reply_markup"].inline_keyboard
        assert len(keyboard) == 4
        assert [button.text for button in keyboard[3]] == [TEST_I18N.get("messages.buttons.listen_word"), "🇮🇷 FA"]

    async def test_a_card_that_is_gone_says_so(self):
        callback, bot = _callback(), _bot()

        await _tap(callback, AUDIO_MENU, _uses(parts=None), bot)

        bot.edit_message_reply_markup.assert_not_awaited()
        assert callback.answer.await_args.args[0] == TEST_I18N.get("callbacks.grade.error_missing")

    async def test_a_double_tap_is_not_an_error(self):
        callback, bot = _callback(), _bot()
        bot.edit_message_reply_markup.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request: message is not modified: specified new message content")

        await _tap(callback, AUDIO_MENU, _uses(parts=[ListenablePart("word")]), bot)

        callback.answer.assert_awaited_once()
        assert not callback.answer.await_args.kwargs.get("show_alert")

    async def test_another_telegram_refusal_says_so_without_escaping(self):
        callback, bot = _callback(), _bot()
        bot.edit_message_reply_markup.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request: message to edit not found")

        await _tap(callback, AUDIO_MENU, _uses(parts=[ListenablePart("word")]), bot)

        assert callback.answer.await_args.kwargs["show_alert"] is True


class TestSending:

    async def test_replies_to_the_card_with_a_voice_message(self):
        bot = _bot()

        await _tap(_callback(), "example", _uses(), bot)

        kwargs = bot.send_voice.await_args.kwargs
        assert kwargs["chat_id"] == 7 and kwargs["reply_parameters"].message_id == 99
        bot.send_audio.assert_not_awaited()

    async def test_remembers_the_file_of_a_word_and_reuses_it(self):
        bot, uses = _bot(), _uses(Clip(audio=b"mp3", word_key="k"))

        await _tap(_callback(), "word", uses, bot)

        uses.remember_telegram_file.assert_awaited_once_with("k", "voice-file")

        again = _bot()
        await handler._deliver(_callback().message, Clip(audio=b"mp3", word_key="k", telegram_file_id="voice-file"),
                               uses, again)
        assert again.send_voice.await_args.kwargs["voice"] == "voice-file"
        uses.remember_telegram_file.assert_awaited_once()

    async def test_a_refused_file_id_is_uploaded_again_and_replaced(self):
        bot, uses = _bot("new-file"), _uses()
        bot.send_voice.side_effect = [
            TelegramBadRequest(method=MagicMock(), message="Bad Request: wrong file identifier/HTTP URL specified"),
            SimpleNamespace(voice=SimpleNamespace(file_id="new-file")),
        ]

        await handler._deliver(_callback().message, Clip(audio=b"mp3", word_key="k", telegram_file_id="old-file"),
                               uses, bot)

        first, second = bot.send_voice.await_args_list
        assert first.kwargs["voice"] == "old-file" and isinstance(second.kwargs["voice"], BufferedInputFile)
        uses.remember_telegram_file.assert_awaited_once_with("k", "new-file")

    async def test_a_user_refusing_voice_keeps_the_stored_file_id(self):
        bot, uses = _bot(), _uses()
        bot.send_voice.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: VOICE_MESSAGES_FORBIDDEN")

        await handler._deliver(_callback().message, Clip(audio=b"mp3", word_key="k", telegram_file_id="old-file"),
                               uses, bot)

        bot.send_voice.assert_awaited_once()
        bot.send_audio.assert_awaited_once()
        uses.remember_telegram_file.assert_not_awaited()

    async def test_only_a_word_is_remembered(self):
        uses = _uses(Clip(audio=b"mp3"))

        await _tap(_callback(), "example", uses, _bot())

        uses.remember_telegram_file.assert_not_awaited()

    async def test_falls_back_to_an_audio_file_when_voice_messages_are_refused(self):
        bot = _bot()
        bot.send_voice.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: VOICE_MESSAGES_FORBIDDEN")
        callback = _callback()

        await _tap(callback, "example", _uses(), bot)

        bot.send_audio.assert_awaited_once()
        assert callback.answer.await_args.kwargs.get("show_alert") is False

    async def test_a_repeat_tap_points_at_the_chat_instead_of_generating(self):
        bot, uses, callback = _bot(), _uses(), _callback()

        await _tap(_callback(), "example", uses, bot)
        await _tap(callback, "example", uses, bot)

        uses.clip.assert_awaited_once()
        assert callback.answer.await_args.args[0] == TEST_I18N.get("callbacks.audio.already_sent")

    async def test_another_part_is_not_a_repeat(self):
        uses = _uses()

        await _tap(_callback(), "example", uses, _bot())
        await _tap(_callback(), "definition", uses, _bot())

        assert uses.clip.await_count == 2


class TestProblems:

    @pytest.mark.parametrize("result, key", [
        (QuotaExceeded(tier="normal", limit=30), "callbacks.audio.limit"),
        (SpeechFailed(), "callbacks.audio.unavailable"),
        (PartMissing(), "callbacks.audio.unavailable"),
    ])
    async def test_show_an_alert_and_can_be_tried_again(self, result, key):
        bot, uses, callback = _bot(), _uses(result), _callback()

        await _tap(callback, "example", uses, bot)
        await _tap(_callback(), "example", uses, bot)

        bot.send_voice.assert_not_awaited()
        assert uses.clip.await_count == 2
        assert callback.answer.await_args.kwargs["show_alert"] is True
        assert callback.answer.await_args.args[0] == TEST_I18N.get(key, limit=30)

    async def test_a_telegram_failure_does_not_escape(self):
        bot, callback = _bot(), _callback()
        bot.send_voice.side_effect = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")

        await _tap(callback, "example", _uses(), bot)

        assert callback.answer.await_args.kwargs["show_alert"] is True

    async def test_an_unknown_part_from_an_old_button_is_refused(self):
        uses, callback = _uses(), _callback()

        await _tap(callback, "nonsense", uses, _bot())

        uses.clip.assert_not_awaited()
        assert callback.answer.await_args.kwargs["show_alert"] is True
