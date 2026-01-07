import logging
from aiogram import Router, Bot
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from flashcard.settings import settings

router = Router()
logger = logging.getLogger(__name__)

@router.error()
async def error_handler(event: ErrorEvent, logger_bot: Bot):
    """
    Global error handler.
    """
    # Log the error with traceback
    logger.exception(f"Update caused error: {event.exception}", exc_info=event.exception)

    # Send error notification to logger bot
    try:
        await logger_bot.send_message(
            chat_id=settings.ADMIN_ID,
            text=(
                f"⚠️ <b>Error Occurred</b>\n"
                f"User ID: {event.update.message.from_user.id if event.update.message else (event.update.callback_query.from_user.id if event.update.callback_query else 'Unknown')}\n"
                f"Update Type: {event.update.event_type}\n"
                f"Exception: {str(event.exception)[:1000]}"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send error notification to logger bot: {e}")

    # Handle specific errors
    if isinstance(event.exception, TelegramForbiddenError):
        # User blocked bot
        logger.info(f"User blocked the bot: {event.update.message.from_user.id}")

    elif isinstance(event.exception, TelegramBadRequest):
        # User sent a message that the bot can't handle or invalid HTML?
        logger.info(f"Bad Request: {event.exception}")