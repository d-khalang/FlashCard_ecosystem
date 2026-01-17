import html
from aiogram import Router, Bot
from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from flashcard.settings import settings
from flashcard.services.i18n import i18n
from flashcard.utils.logger import get_logger

router = Router()
logger = get_logger(__name__)

@router.error()
async def error_handler(event: ErrorEvent, logger_bot: Bot):
    """
    Global error handler.
    """
    # Log the error with traceback
    logger.exception(f"Update caused error: {event.exception}", exc_info=event.exception)

    # Send error notification to logger bot
    try:
        exception_text = html.escape(str(event.exception)[:1000])
        await logger_bot.send_message(
            chat_id=settings.ADMIN_ID,
            text=(
                f"⚠️ <b>Error Occurred</b>\n"
                f"User ID: {event.update.message.from_user.id if event.update.message else (event.update.callback_query.from_user.id if event.update.callback_query else 'Unknown')}\n"
                f"Update Type: {event.update.event_type}\n"
                f"Exception: {exception_text}"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send error notification to logger bot: {e}")

    # Handle specific errors
    if isinstance(event.exception, TelegramForbiddenError):
        # User blocked bot
        if event.update.message:
            logger.info(f"User blocked the bot: {event.update.message.from_user.id}")
        
    elif isinstance(event.exception, TelegramBadRequest):
        # User sent a message that the bot can't handle or invalid HTML?
        logger.info(f"Bad Request: {event.exception}")
    
    # Notify user about the error
    try:
        user_id = None
        if event.update.message:
            user_id = event.update.message.from_user.id
            await event.update.message.answer(i18n.get("messages.errors.service_unavailable"))
        elif event.update.callback_query:
            user_id = event.update.callback_query.from_user.id
            # Answer callback query to stop loading animation
            await event.update.callback_query.message.answer(i18n.get("messages.errors.service_unavailable"))
            await event.update.callback_query.answer()
            
    except Exception as e:
        # If we can't notify the user (e.g. blocked bot), just log it
        logger.warning(f"Failed to notify user {user_id} about error: {e}")