"""
Shared Telegram callback helpers.

Utilities that any handler dealing with CallbackQuery can reuse.
"""
import asyncio
from typing import Awaitable

from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

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


async def safe_call(coro: Awaitable, *, timeout: float = 5) -> None:
    """
    Await *coro* with a timeout, suppressing ``TimeoutError``.

    Designed for fire-and-forget error-recovery calls (e.g. answering a
    callback or notifying the admin) where a stall must never cascade.
    """
    with asyncio.suppress(asyncio.TimeoutError):
        async with asyncio.timeout(timeout):
            await coro
