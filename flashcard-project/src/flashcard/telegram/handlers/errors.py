import html
from aiogram import Router, Bot
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from google.genai.errors import APIError as GeminiAPIError
from pymongo.errors import PyMongoError

from flashcard.services.i18n import i18n
from flashcard.telegram.helpers.callback_utils import safe_answer_callback
from flashcard.utils.logger import get_logger

router = Router()
logger = get_logger(__name__)

# Ordered mapping: first match wins.
# Handlers that catch locally never reach here; only uncaught exceptions are mapped.
_ERROR_MESSAGE_MAP: list[tuple[type, str]] = [
    (GeminiAPIError, "messages.errors.llm_unavailable"),
    (PyMongoError,   "messages.errors.db_unavailable"),
]

def _user_message_key(exception: BaseException) -> str:
    """Return the i18n key for the most specific match, or the generic fallback."""
    for exc_type, key in _ERROR_MESSAGE_MAP:
        if isinstance(exception, exc_type):
            return key
    return "messages.errors.service_unavailable"

@router.error()
async def error_handler(event: ErrorEvent, logger_bot: Bot, trace_id: str | None = None):
    """
    Global error handler.
    """
    # Log the error with traceback
    logger.exception(f"Update caused error: {event.exception}", exc_info=event.exception)

    # Send error notification to logger bot
    try:
        from flashcard.utils.logger import notify_admin_with_trace
        resolved_trace_id = trace_id or getattr(event.exception, "trace_id", None)
        exception_text = html.escape(str(event.exception)[:1000])
        await notify_admin_with_trace(
            logger_bot,
            text=(
                f"⚠️ <b>Error Occurred</b>\n"
                f"User ID: {event.update.message.from_user.id if event.update.message else (event.update.callback_query.from_user.id if event.update.callback_query else 'Unknown')}\n"
                f"Update Type: {event.update.event_type}\n"
                f"Exception: {exception_text}"
            ),
            trace_id=resolved_trace_id
        )
    except Exception as e:
        logger.error(f"Failed to send error notification to logger bot: {e}")

    # Handle specific errors
    if isinstance(event.exception, TelegramForbiddenError):
        # User blocked bot
        if event.update.message:
            logger.warning(f"User blocked the bot: {event.update.message.from_user.id}")
        
    elif isinstance(event.exception, TelegramBadRequest):
        # User sent a message that the bot can't handle or invalid HTML?
        logger.warning(f"Bad Request: {event.exception}")
    
    # Notify user with the most specific message available
    user_message = i18n.get(_user_message_key(event.exception))
    try:
        user_id = None
        if event.update.message:
            user_id = event.update.message.from_user.id
            await event.update.message.answer(user_message)
        elif event.update.callback_query:
            user_id = event.update.callback_query.from_user.id
            # Answer callback query to stop loading animation
            if event.update.callback_query.message:
                await event.update.callback_query.message.answer(user_message)
            await safe_answer_callback(event.update.callback_query)
            
    except Exception as e:
        # If we can't notify the user (e.g. blocked bot), just log it
        logger.warning(f"Failed to notify user {user_id} about error: {e}")
        
    return True
