import asyncio
import html
from typing import Any

from aiogram import Bot

from flashcard.utils.logger import get_logger, notify_admin_with_trace

logger = get_logger(__name__)


def install_asyncio_exception_handler(logger_bot: Bot | None = None) -> None:
    """
    Install a loop-level handler so background task errors are logged by app logger.

    This captures exceptions such as "Task exception was never retrieved" that happen
    outside aiogram update handlers (for example, chat action worker tasks).
    """
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    if previous_handler and getattr(previous_handler, "_flashcard_asyncio_handler", False):
        return

    def _exception_handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        def _call_previous_handler() -> None:
            if previous_handler is None:
                return
            try:
                previous_handler(_loop, context)
            except Exception:
                logger.exception("Previous asyncio exception handler failed")

        exception = context.get("exception")
        if isinstance(exception, asyncio.CancelledError):
            _call_previous_handler()
            return

        message = context.get("message", "Unhandled asyncio exception")
        future = context.get("future") or context.get("task")
        future_repr = repr(future) if future is not None else "n/a"

        if exception is not None:
            logger.error(
                f"Asyncio background task error: {message} | future={future_repr}",
                exc_info=exception,
            )
        else:
            logger.error(f"Asyncio background task error: {message} | future={future_repr}")

        if logger_bot is None:
            _call_previous_handler()
            return

        error_text = html.escape(
            f"{type(exception).__name__}: {exception}" if exception is not None else message
        )[:1000]
        if _loop.is_closed():
            logger.warning("Skipping async admin notification: event loop is closed")
            _call_previous_handler()
            return

        notify_coro = notify_admin_with_trace(
            logger_bot,
            text=f"<b>Async Task Error</b>\n{error_text}",
        )
        try:
            _loop.create_task(notify_coro)
        except RuntimeError as e:
            # Avoid "coroutine was never awaited" if scheduling fails during shutdown.
            notify_coro.close()
            logger.warning(f"Skipping async admin notification: failed to schedule task: {e}")

        _call_previous_handler()

    setattr(_exception_handler, "_flashcard_asyncio_handler", True)
    loop.set_exception_handler(_exception_handler)
