"""
The stand-in bot for planned maintenance (`flashcard-maintenance`).

While the real bot is stopped for long server work, this runs with the same token and
answers every message, button and inline search with one "under maintenance" note.
It needs no database, LLM or other service, so it keeps working while they are down.
What users send meanwhile is answered, not kept: the real bot does not run it later.

Same delivery as the real bot: a webhook bot sets the same webhook (the real bot
removes it when it stops, and sets it again when it starts); a polling bot polls.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher, Router
from aiogram.types import CallbackQuery, InlineQuery, Message, Update
from fastapi import FastAPI, Header, HTTPException, Request

from flashcard.api.routes.webhook import _secret_matches
from flashcard.language import LanguageConfig
from flashcard.services.i18n import I18nService
from flashcard.settings import Settings, get_setting
from flashcard.telegram.session import build_ipv4_session
from flashcard.utils.logger import configure_log_level, get_logger

logger = get_logger(__name__)

NOTE_KEY = "messages.maintenance"


def build_maintenance_dispatcher(note: str) -> Dispatcher:
    """Every message, button and inline search gets `note`; nothing else happens."""
    router = Router()

    @router.message()
    async def on_message(message: Message) -> None:
        await message.answer(note)

    @router.callback_query()
    async def on_button(callback: CallbackQuery) -> None:
        # Telegram limits button alerts to 200 characters.
        await callback.answer(note[:200], show_alert=True)

    @router.inline_query()
    async def on_inline(inline_query: InlineQuery) -> None:
        await inline_query.answer([], cache_time=60, is_personal=True)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


def create_app(settings: Settings | None = None, bot: Bot | None = None) -> FastAPI:
    settings = settings or get_setting()
    configure_log_level(settings.LOG_LEVEL)
    note = I18nService.for_language(LanguageConfig.from_settings(settings)).get(NOTE_KEY)
    dispatcher = build_maintenance_dispatcher(note)
    bot = bot or Bot(token=settings.BOT_TOKEN, session=build_ipv4_session())
    mode = settings.TELEGRAM_DELIVERY_MODE
    allowed_updates = dispatcher.resolve_used_update_types()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        polling = None
        if mode == "webhook":
            await bot.set_webhook(url=settings.webhook_url, secret_token=settings.WEBHOOK_SECRET,
                                  allowed_updates=allowed_updates)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            polling = asyncio.create_task(
                dispatcher.start_polling(bot, allowed_updates=allowed_updates, handle_signals=False))
        logger.info("Maintenance bot running (%s): every update gets the maintenance note", mode)
        try:
            yield
        finally:
            if polling:
                polling.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await polling
            # The webhook stays: the real bot replaces it when it starts again.
            await bot.session.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    # Both paths answer, so the bot's own Docker health check works unchanged.
    @app.get("/health")
    @app.get("/health/ready")
    async def health() -> dict:
        return {"status": "ok", "mode": "maintenance"}

    @app.post(settings.WEBHOOK_PATH)
    async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)) -> dict:
        if mode != "webhook" or not _secret_matches(x_telegram_bot_api_secret_token, settings.WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="Invalid secret token")
        try:
            update = Update(**await request.json())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid update payload")
        try:
            await dispatcher.feed_update(bot, update)
        except Exception:
            # Answer 200 anyway: a retried update would only get the same note again.
            logger.warning("Maintenance note not sent", exc_info=True)
        return {"ok": True}

    return app


def main() -> None:
    uvicorn.run("flashcard.maintenance:create_app", factory=True, host="0.0.0.0", port=get_setting().PORT)
