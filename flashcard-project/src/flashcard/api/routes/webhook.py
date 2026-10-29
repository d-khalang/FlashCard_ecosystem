import html
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from aiogram.types import Update
from flashcard.utils.logger import get_logger, notify_admin_with_trace

logger = get_logger(__name__)


def build_router(path: str) -> APIRouter:
    """The webhook route at `WEBHOOK_PATH`; the secret is read from `app.state.webhook_secret`."""
    router = APIRouter()
    router.add_api_route(path, webhook_handler, methods=["POST"])
    return router


def _secret_matches(received: str | None, expected: str) -> bool:
    """Constant-time check. A missing header or an unset secret (polling mode) never matches."""
    if not received or not expected:
        return False
    return secrets.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


async def webhook_handler(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    if not _secret_matches(x_telegram_bot_api_secret_token, request.app.state.webhook_secret):
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

    # Set by the FastAPI lifespan (running_bot)
    telegram = request.app.state.telegram

    try:
        await telegram.dispatcher.feed_update(telegram.bot, update, **telegram.handler_data)
    except Exception as e:
        logger.exception("Webhook update processing failed")
        try:
            error_text = html.escape(f"{type(e).__name__}: {str(e)}")[:1000]
            await notify_admin_with_trace(
                telegram.logger_bot,
                admin_id=telegram.admin_id,
                text=f"<b>Webhook Processing Error</b>\n{error_text}",
            )
        except Exception as notify_error:
            logger.warning(f"Failed to notify admin about webhook error: {notify_error}")
        raise HTTPException(status_code=500, detail="Failed to process update")

    return {"ok": True}
