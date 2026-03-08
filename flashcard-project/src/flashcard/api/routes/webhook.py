import html

from fastapi import APIRouter, Header, HTTPException, Request
from aiogram.types import Update
from flashcard.settings import settings
from flashcard.utils.logger import get_logger, notify_admin_with_trace

router = APIRouter()
logger = get_logger(__name__)

@router.post(settings.WEBHOOK_PATH)
async def webhook_handler(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        data = await request.json()
    except Exception as e:
        logger.warning("Invalid webhook JSON payload", exc_info=e)
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        update = Update(**data)
    except Exception as e:
        logger.warning("Invalid webhook update payload", exc_info=e)
        raise HTTPException(status_code=400, detail="Invalid update payload")

    # Get bot and dispatcher from app state (set during init_telegram_bot)
    bot = request.app.state.bot
    dp = request.app.state.dispatcher
    dispatcher_data = getattr(request.app.state, "dispatcher_data", {})

    try:
        # Feed update to dispatcher
        await dp.feed_update(bot, update, **dispatcher_data)
    except Exception as e:
        logger.exception("Webhook update processing failed")
        logger_bot = getattr(request.app.state, "logger_bot", None)
        if logger_bot is not None:
            try:
                error_text = html.escape(f"{type(e).__name__}: {str(e)}")[:1000]
                await notify_admin_with_trace(
                    logger_bot,
                    text=f"<b>Webhook Processing Error</b>\n{error_text}",
                )
            except Exception as notify_error:
                logger.warning(f"Failed to notify admin about webhook error: {notify_error}")
        raise HTTPException(status_code=500, detail="Failed to process update")

    return {"ok": True}
