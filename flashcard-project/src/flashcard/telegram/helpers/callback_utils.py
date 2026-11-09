"""
Shared Telegram callback helpers.

Utilities that any handler dealing with CallbackQuery can reuse.
"""
import asyncio
import contextlib
from typing import Awaitable

from aiogram import Bot
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from flashcard.utils.logger import get_logger

logger = get_logger(__name__)


async def safe_answer_callback(callback: CallbackQuery, text: str = "", show_alert: bool = False) -> None:
    """
    Answer a callback query, silently ignoring the "query is too old" error.

    Telegram callback queries expire quickly (~30 s).  If a handler takes
    longer than that (e.g. due to a network blip), answering raises
    ``TelegramBadRequest``; this wrapper swallows **only** that expected case
    and re-raises everything else.
    """
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if "query is too old" in error_text or "query id is invalid" in error_text:
            logger.warning("Skipped callback.answer because callback query expired.")
            return
        raise


async def clear_buttons(callback: CallbackQuery, bot: Bot) -> None:
    """
    Remove the buttons of a card they can no longer act on, keeping the text.

    Cosmetic, so a failure is only logged. Goes through the bot because an old message
    arrives as InaccessibleMessage, which has a chat and an id but no edit methods.
    """
    try:
        await bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=None,
        )
    except TelegramAPIError as e:
        logger.warning(f"Skipped clearing dead buttons: {e}")


async def safe_call(coro: Awaitable, *, timeout: float = 5) -> None:
    """
    Await *coro* with a timeout, suppressing ``TimeoutError``.

    Designed for fire-and-forget error-recovery calls (e.g. answering a
    callback or notifying the admin) where a stall must never cascade.
    """
    with contextlib.suppress(asyncio.TimeoutError):
        async with asyncio.timeout(timeout):
            await coro
