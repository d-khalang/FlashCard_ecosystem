import asyncio
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from flashcard.services.i18n import i18n
from flashcard.telegram.helpers.callback_utils import safe_answer_callback
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

# Short user-facing message when a handler exceeds the timeout.
_TIMEOUT_KEY = "messages.errors.service_unavailable"


class HandlerTimeoutMiddleware(BaseMiddleware):
    """
    Caps every message/callback handler to *timeout* seconds.

    If the handler exceeds the deadline the user receives an
    instant "try again later" reply instead of hanging for 60s+.
    Applied once in bot.py — no per-handler changes needed.
    """

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await asyncio.wait_for(handler(event, data), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Handler timed out after {self.timeout}s for "
                f"{type(event).__name__}"
            )
            # Best-effort user notification — don't let this itself block
            try:
                msg = i18n.get(_TIMEOUT_KEY)
                if isinstance(event, Message):
                    await event.answer(msg)
                elif isinstance(event, CallbackQuery):
                    await safe_answer_callback(event, msg, show_alert=True)
            except Exception:
                pass  # Network might be down — nothing we can do

            return None  # Swallow so aiogram doesn't re-raise
