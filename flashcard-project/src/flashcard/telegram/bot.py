import asyncio
import contextlib
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
    unknown,
    creation,
    errors
)
from flashcard.services.expression import ExpressionService
from flashcard.services.verb import VerbService
from flashcard.services.user import UserService

def build_bot_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

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
    dp.include_router(verb.router)       # /verb + conjugation callback
    dp.include_router(story.router)      # /story
    dp.include_router(collection.router) # /import, /list_my_flashcards
    
    # 4. Unknown Commands (catch-all for unrecognized /commands)
    dp.include_router(unknown.router)
    
    # 5. Content Creation (Catch-all for text messages)
    dp.include_router(creation.router)
    
    # 6. Errors (Last resort)
    dp.include_router(errors.router)

    return bot, dp
async def init_telegram_bot(app: FastAPI, settings):
    bot, dp = build_bot_dispatcher()
    app.state.bot = bot
    app.state.dispatcher = dp

    logger_bot = Bot(token=settings.LOGGER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    app.state.logger_bot = logger_bot

    # Initialize Services
    # May later be removed from app.state if not needed globally as they are passed to handlers
    mongo_client, db, cols = await init_and_get_mongo(settings)
    app.state.mongo_client = mongo_client
    app.state.db = db
    app.state.cols = cols

    http_client = await init_and_get_http_client()
    app.state.http_client = http_client

    verb_service = VerbService(cols=app.state.cols, http_client=app.state.http_client)
    expression_service = ExpressionService(cols=app.state.cols)
    user_service = UserService(cols=app.state.cols)
    llm_service = LLMService()
    app.state.expression_service = expression_service
    app.state.user_service = user_service
    app.state.llm_service = llm_service

    # Webhook vs Polling
    # Use polling by default unless WEBHOOK_URL is set/configured
    # For now, we keep the existing logic: polling in background task
    
    # If we wanted to enable webhook:
    # webhook_url = settings.WEBHOOK_URL
    # if webhook_url:
    #     await bot.set_webhook(...)
    # else:
    
    # Run polling in background
    app.state.polling_task = asyncio.create_task(
        dp.start_polling(
            bot, 
            cols=cols, 
            http_client=http_client,
            logger_bot=logger_bot,
            verb_service=verb_service,
            expression_service=expression_service,
            user_service=user_service,
            llm_service=llm_service
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
            llm_service=llm_service,
            admin_id=settings.ADMIN_ID
        )
    )


async def close_telegram_bot(app: FastAPI):
    await close_mongo_on_client(app.state.mongo_client)
    
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
    await bot.session.close()

    logger_bot: Bot = app.state.logger_bot
    await logger_bot.session.close()


async def init_telegram_without_fastapi(settings):
    bot, dp = build_bot_dispatcher()

    logger_bot = Bot(token=settings.LOGGER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # Initialize Services
    # May later be removed from app.state if not needed globally as they are passed to handlers
    mongo_client, db, cols = await init_and_get_mongo(settings)

    http_client = await init_and_get_http_client()

    verb_service = VerbService(cols=cols, http_client=http_client)
    expression_service = ExpressionService(cols=cols)
    user_service = UserService(cols=cols)
    llm_service = LLMService()

    # Run polling in background
    polling_task = asyncio.create_task(
        dp.start_polling(
            bot, 
            cols=cols, 
            http_client=http_client,
            logger_bot=logger_bot,
            verb_service=verb_service,
            expression_service=expression_service,
            user_service=user_service,
            llm_service=llm_service
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
