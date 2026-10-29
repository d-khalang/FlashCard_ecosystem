import asyncio
import contextlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional
import socket
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.chat_action import ChatActionMiddleware

from flashcard.composition import Core, build_core, open_resources
from flashcard.language import LanguageConfig
from flashcard.settings import settings
from flashcard.telegram.handlers import (
    user_settings, 
    feedback, 
    reply_commands,
    start,
    review,
    verb,
    story,
    collection,
    inline_remove,
    unknown,
    creation,
    errors
)
from flashcard.telegram.middlewares.trace_middleware import TraceMiddleware
from flashcard.telegram.middlewares.timeout_middleware import HandlerTimeoutMiddleware
from flashcard.services.trace_logger import get_trace_logger
from flashcard.utils.asyncio_errors import install_asyncio_exception_handler

def _build_ipv4_session() -> "AiohttpSession":
    """Build an aiogram session that forces IPv4.

    Docker's default bridge network has no IPv6 routing, so aiohttp
    may occasionally attempt an IPv6 connection to api.telegram.org
    that silently hangs until the OS timeout (20-60 s).  Pinning to
    AF_INET eliminates the issue entirely.
    """
    from aiogram.client.session.aiohttp import AiohttpSession

    session = AiohttpSession()
    # Inject IPv4 family into the lazy connector initialization
    # Note: Modern aiogram (3.x) doesn't take 'connector' in __init__, so we touch internal state
    session._connector_init["family"] = socket.AF_INET

    from flashcard.utils.logger import get_logger
    get_logger(__name__).info("Telegram session: forcing IPv4 (AF_INET)")
    return session


def build_bot_dispatcher(language: LanguageConfig) -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=_build_ipv4_session(),
    )
    dp = Dispatcher()

    # Start tracing before anything else
    dp.update.middleware(TraceMiddleware())

    # Global 10s timeout — users get instant error instead of 60s+ hang
    dp.message.middleware(HandlerTimeoutMiddleware(timeout=10.0))
    dp.callback_query.middleware(HandlerTimeoutMiddleware(timeout=10.0))
    dp.inline_query.middleware(HandlerTimeoutMiddleware(timeout=10.0))

    dp.message.middleware(ChatActionMiddleware())
    
    # Include routers in strict order of priority
    # 1. Settings & Feedback (High priority FSMs)
    dp.include_router(user_settings.router)
    dp.include_router(feedback.router)
    
    # 2. Reply Commands (Text replies that map to commands)
    dp.include_router(reply_commands.router)
    
    # 3. Domain Features
    dp.include_router(start.router)      # /start, /help
    dp.include_router(review.router)     # /get + grade callback
    if language.conjugation:
        dp.include_router(verb.router)   # /verb + conjugation callback
    dp.include_router(story.router)      # /story
    dp.include_router(collection.router) # /import, /list_my_flashcards
    dp.include_router(inline_remove.router) # inline query card removal
    
    # 4. Unknown Commands (catch-all for unrecognized /commands)
    dp.include_router(unknown.router)
    
    # 5. Content Creation (Catch-all for text messages)
    dp.include_router(creation.router)
    
    # 6. Errors (Last resort)
    dp.include_router(errors.router)

    return bot, dp


def get_allowed_updates(dp: Dispatcher) -> list[str]:
    """
    Resolve the concrete update types used by the registered routers.

    Telegram keeps the previous webhook subscription if ``allowed_updates``
    is omitted, so we must send the full current list on every webhook setup.
    """
    return dp.resolve_used_update_types()


@dataclass
class TelegramRuntime:
    bot: Bot
    logger_bot: Bot
    dispatcher: Dispatcher
    handler_data: dict
    mode: str
    polling_task: Optional[asyncio.Task] = None
    scheduler_task: Optional[asyncio.Task] = None


async def start_telegram(core: Core, settings, mode: str) -> TelegramRuntime:
    """Start the bot (webhook or polling) and the review scheduler on top of the core."""
    bot, dp = build_bot_dispatcher(core.language)
    logger_bot = Bot(
        token=settings.LOGGER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=_build_ipv4_session(),
    )
    install_asyncio_exception_handler(logger_bot=logger_bot)
    runtime = TelegramRuntime(
        bot=bot, logger_bot=logger_bot, dispatcher=dp,
        handler_data=core.handler_data(logger_bot), mode=mode,
    )

    if mode == "webhook":
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            allowed_updates=get_allowed_updates(dp),
        )
    else:
        # Polling cannot run while a webhook is active.
        await bot.delete_webhook(drop_pending_updates=False)
        runtime.polling_task = asyncio.create_task(
            dp.start_polling(
                bot,
                allowed_updates=get_allowed_updates(dp),
                **runtime.handler_data,
            )
        )

    from flashcard.scheduler.scheduler import scheduler_loop
    runtime.scheduler_task = asyncio.create_task(
        scheduler_loop(
            bot=bot,
            logger_bot=logger_bot,
            user_service=core.user_service,
            review_use_cases=core.review_use_cases,
            language=core.language,
            admin_id=settings.ADMIN_ID,
            pause_rule=settings.REVIEW_PAUSE_RULE,
        )
    )
    return runtime


async def stop_telegram(runtime: TelegramRuntime) -> None:
    for task in (runtime.scheduler_task, runtime.polling_task):
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    if runtime.mode == "webhook":
        with contextlib.suppress(Exception):
            await runtime.bot.delete_webhook(drop_pending_updates=False)
    await runtime.bot.session.close()
    await runtime.logger_bot.session.close()

    # Mongo and the HTTP client belong to open_resources, which closes them after this.
    get_trace_logger().shutdown()


@asynccontextmanager
async def running_bot(settings, mode: str):
    """The whole bot: shared clients, the core, then Telegram. Closed in reverse order."""
    language = LanguageConfig.from_settings(settings)
    async with open_resources(settings) as resources:
        core = build_core(resources.cols, resources.http_client, settings, language)
        runtime = await start_telegram(core, settings, mode)
        try:
            yield resources, runtime
        finally:
            await stop_telegram(runtime)
