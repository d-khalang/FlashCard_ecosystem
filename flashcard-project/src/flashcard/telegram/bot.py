import asyncio
import contextlib
import socket
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.chat_action import ChatActionMiddleware
from fastapi import FastAPI

from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
from flashcard.services.http_client import close_http_client_on_client, init_and_get_http_client
from flashcard.services.llm.llm import LLMService
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
from flashcard.services.expression import ExpressionService
from flashcard.services.verb import VerbService
from flashcard.services.user import UserService
from flashcard.services.consumption import ConsumptionService
from flashcard.services.trace_logger import get_trace_logger
from flashcard.services.language_validation import get_language_validator
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


def build_bot_dispatcher() -> tuple[Bot, Dispatcher]:
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
    if getattr(settings, "ENABLE_CONJUGATION", True):
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


def build_dispatcher_data(
    cols,
    http_client,
    logger_bot,
    verb_service,
    expression_service,
    user_service,
    consumption_service,
    llm_service,
    language_validator
) -> dict:
    return {
        "cols": cols,
        "http_client": http_client,
        "logger_bot": logger_bot,
        "verb_service": verb_service,
        "expression_service": expression_service,
        "user_service": user_service,
        "consumption_service": consumption_service,
        "llm_service": llm_service,
        "language_validator": language_validator,
    }


async def init_telegram_bot(app: FastAPI, settings):
    bot, dp = build_bot_dispatcher()
    app.state.bot = bot
    app.state.dispatcher = dp

    logger_bot = Bot(
        token=settings.LOGGER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=_build_ipv4_session(),
    )
    app.state.logger_bot = logger_bot
    install_asyncio_exception_handler(logger_bot=logger_bot)

    # Initialize Services
    # May later be removed from app.state if not needed globally as they are passed to handlers
    mongo_client, db, cols = await init_and_get_mongo(settings)
    app.state.mongo_client = mongo_client
    app.state.db = db
    app.state.cols = cols

    http_client = await init_and_get_http_client()
    app.state.http_client = http_client

    verb_service = (
        VerbService(cols=app.state.cols, http_client=app.state.http_client)
        if getattr(settings, "ENABLE_CONJUGATION", True)
        else None
    )
    expression_service = ExpressionService(cols=app.state.cols)
    consumption_service = ConsumptionService(cols=app.state.cols)
    user_service = UserService(cols=app.state.cols, consumption_service=consumption_service)
    llm_service = LLMService()
    language_validator = get_language_validator(settings)
    app.state.expression_service = expression_service
    app.state.user_service = user_service
    app.state.consumption_service = consumption_service
    app.state.llm_service = llm_service

    dispatcher_data = build_dispatcher_data(
        cols=cols,
        http_client=http_client,
        logger_bot=logger_bot,
        verb_service=verb_service,
        expression_service=expression_service,
        user_service=user_service,
        consumption_service=consumption_service,
        llm_service=llm_service,
        language_validator=language_validator,
    )
    app.state.dispatcher_data = dispatcher_data

    # Run either webhook or polling, based on explicit mode.
    if settings.TELEGRAM_DELIVERY_MODE == "webhook":
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            allowed_updates=get_allowed_updates(dp),
        )
    else:
        # Polling cannot run while a webhook is active.
        await bot.delete_webhook(drop_pending_updates=False)
        app.state.polling_task = asyncio.create_task(
            dp.start_polling(
                bot,
                allowed_updates=get_allowed_updates(dp),
                **dispatcher_data,
            )
        )
    
    # Start scheduler in background
    from flashcard.scheduler.scheduler import scheduler_loop
    app.state.scheduler_task = asyncio.create_task(
        scheduler_loop(
            bot=bot,
            logger_bot=logger_bot,
            expression_service=expression_service,
            user_service=user_service,
            consumption_service=consumption_service,
            llm_service=llm_service,
            admin_id=settings.ADMIN_ID
        )
    )


async def close_telegram_bot(app: FastAPI):
    # Stop scheduler task
    scheduler_task = getattr(app.state, "scheduler_task", None)
    if scheduler_task:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task

    # Stop polling task
    task = getattr(app.state, "polling_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        
    bot: Bot = app.state.bot
    if settings.TELEGRAM_DELIVERY_MODE == "webhook":
        with contextlib.suppress(Exception):
            await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()

    logger_bot: Bot = app.state.logger_bot
    await logger_bot.session.close()

    await close_mongo_on_client(app.state.mongo_client)
    await close_http_client_on_client(app.state.http_client)

    get_trace_logger().shutdown()


async def init_telegram_without_fastapi(settings):
    bot, dp = build_bot_dispatcher()

    logger_bot = Bot(
        token=settings.LOGGER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=_build_ipv4_session(),
    )
    install_asyncio_exception_handler(logger_bot=logger_bot)

    # Initialize Services
    # May later be removed from app.state if not needed globally as they are passed to handlers
    mongo_client, db, cols = await init_and_get_mongo(settings)

    http_client = await init_and_get_http_client()

    verb_service = (
        VerbService(cols=cols, http_client=http_client)
        if getattr(settings, "ENABLE_CONJUGATION", True)
        else None
    )
    expression_service = ExpressionService(cols=cols)
    consumption_service = ConsumptionService(cols=cols)
    user_service = UserService(cols=cols, consumption_service=consumption_service)
    llm_service = LLMService()
    language_validator = get_language_validator(settings)

    # Polling cannot run while a webhook is active.
    await bot.delete_webhook(drop_pending_updates=False)

    # Run polling in background
    polling_task = asyncio.create_task(
        dp.start_polling(
            bot, 
            allowed_updates=get_allowed_updates(dp),
            cols=cols, 
            http_client=http_client,
            logger_bot=logger_bot,
            verb_service=verb_service,
            expression_service=expression_service,
            user_service=user_service,
            consumption_service=consumption_service,
            llm_service=llm_service,
            language_validator=language_validator,
        )
    )
    
    # Start scheduler in background
    from flashcard.scheduler.scheduler import scheduler_loop
    scheduler_task = asyncio.create_task(
        scheduler_loop(
            bot=bot,
            logger_bot=logger_bot,
            expression_service=expression_service,
            user_service=user_service,
            consumption_service=consumption_service,
            llm_service=llm_service,
            admin_id=settings.ADMIN_ID
        )
    )

    return {
        "mongo_client": mongo_client,
        "bot": bot,
        "logger_bot": logger_bot,
        "http_client": http_client,
        "polling_task": polling_task,
        "scheduler_task": scheduler_task
    }

async def close_telegram_without_fastapi(resources: dict):
    # Stop scheduler task
    if "scheduler_task" in resources:
        task = resources["scheduler_task"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    
    # Stop polling task
    if "polling_task" in resources:
        task = resources["polling_task"]
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    await close_mongo_on_client(resources["mongo_client"])
    
    await close_http_client_on_client(resources["http_client"])
    await resources["bot"].session.close()
    await resources["logger_bot"].session.close()
    
    get_trace_logger().shutdown()
