"""
The grade buttons of a bot-delivered card follow what happens to it in the app.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramBadRequest

from flashcard.miniapp.bot_buttons import BotCardButtons
from flashcard.services.i18n import I18nService
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.language import LanguageConfig
from flashcard.settings import get_setting

USER = 42
MESSAGE_ID = 555
EXPRESSION_ID = "507f1f77bcf86cd799439011"


def _i18n():
    return I18nService.for_language(LanguageConfig.from_settings(get_setting()))


def _card(delivery_id=MESSAGE_ID):
    return SimpleNamespace(delivery_id=delivery_id, expression_id=EXPRESSION_ID, direction="reverse")


def _buttons():
    bot = MagicMock()
    bot.edit_message_reply_markup = AsyncMock()
    bot.session.close = AsyncMock()
    return BotCardButtons(bot), bot


class TestBotCardButtons:

    async def test_removing_clears_the_keyboard_of_the_users_message(self):
        buttons, bot = _buttons()

        buttons.remove(USER, MESSAGE_ID)
        await buttons.close()

        kwargs = bot.edit_message_reply_markup.await_args.kwargs
        assert (kwargs["chat_id"], kwargs["message_id"], kwargs["reply_markup"]) == (USER, MESSAGE_ID, None)

    async def test_restoring_puts_back_the_cards_own_keyboard(self):
        buttons, bot = _buttons()
        i18n = _i18n()

        buttons.restore(USER, _card(), i18n)
        await buttons.close()

        kwargs = bot.edit_message_reply_markup.await_args.kwargs
        assert kwargs["message_id"] == MESSAGE_ID
        assert kwargs["reply_markup"] == get_review_keyboard(i18n, EXPRESSION_ID, direction="reverse")

    async def test_a_card_delivered_in_the_app_has_no_message_to_touch(self):
        buttons, bot = _buttons()

        buttons.remove(USER, -7)
        buttons.restore(USER, _card(delivery_id=-7), _i18n())
        await buttons.close()

        bot.edit_message_reply_markup.assert_not_awaited()

    async def test_a_quick_grade_and_undo_run_in_order_however_slow_the_first_is(self):
        buttons, bot = _buttons()
        order = []
        release = asyncio.Event()

        async def edit(**kwargs):
            if kwargs["reply_markup"] is None:
                await release.wait()
            order.append("keyboard" if kwargs["reply_markup"] else "none")

        bot.edit_message_reply_markup.side_effect = edit
        buttons.remove(USER, MESSAGE_ID)
        buttons.restore(USER, _card(), _i18n())
        await asyncio.sleep(0)
        release.set()
        await buttons.close()

        assert order == ["none", "keyboard"]

    async def test_a_failed_call_does_not_stop_the_next_one(self):
        buttons, bot = _buttons()
        bot.edit_message_reply_markup.side_effect = [
            TelegramBadRequest(method=MagicMock(), message="Bad Request: message to edit not found"), None]

        buttons.remove(USER, MESSAGE_ID)
        buttons.restore(USER, _card(), _i18n())
        await buttons.close()

        assert bot.edit_message_reply_markup.await_count == 2

    async def test_finished_work_is_forgotten_and_close_closes_the_session(self):
        buttons, bot = _buttons()

        buttons.remove(USER, MESSAGE_ID)
        await buttons.close()
        await asyncio.sleep(0)

        assert not buttons._tasks and not buttons._last
        bot.session.close.assert_awaited_once()

    async def test_wait_idle_returns_once_every_call_is_done_without_closing(self):
        buttons, bot = _buttons()
        release = asyncio.Event()

        async def edit(**kwargs):
            await release.wait()

        bot.edit_message_reply_markup.side_effect = edit
        buttons.remove(USER, MESSAGE_ID)
        buttons.restore(USER, _card(), _i18n())
        waiting = asyncio.create_task(buttons.wait_idle())
        await asyncio.sleep(0)
        assert not waiting.done()

        release.set()
        await asyncio.wait_for(waiting, timeout=1)

        assert bot.edit_message_reply_markup.await_count == 2
        bot.session.close.assert_not_awaited()
