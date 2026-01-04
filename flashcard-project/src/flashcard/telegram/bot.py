import asyncio
import contextlib
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.chat_action import ChatActionMiddleware
from fastapi import FastAPI

from flashcard.settings import settings
from flashcard.telegram.handlers import messages, commands, callbacks, errors

# def build_bot_dispatcher() -> tuple[Bot, Dispatcher]:
#     bot = Bot(token=settings.BOT_TOKEN)
#     dp = Dispatcher()
    
#     # Include routers
#     dp.include_router(messages.router)
#     dp.include_router(callbacks.router)
    
#     return bot, dp

def build_bot_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher()

    dp.message.middleware(ChatActionMiddleware())
    
    # Include routers
    dp.include_router(commands.router)
    dp.include_router(messages.router)
    dp.include_router(callbacks.router)
    dp.include_router(errors.router)

    return bot, dp


# async def init_telegram_bot(app: FastAPI, settings):
#     bot, dp = build_bot_dispatcher()
    
#     # Store in app.state for access in handlers/other parts of the app
#     app.state.bot = bot
#     app.state.dispatcher = dp
    
#     # Set webhook
#     webhook_url = settings.webhook_url
#     print(f"Setting webhook to: {webhook_url}")
#     await bot.set_webhook(
#         url=webhook_url,
#         secret_token=settings.WEBHOOK_SECRET,
#         drop_pending_updates=True, # optional, good for dev
#         allowed_updates=["message", "callback_query"]
#     )


async def init_telegram_bot(app: FastAPI, settings):
    bot, dp = build_bot_dispatcher()
    app.state.bot = bot
    app.state.dispatcher = dp

    logger_bot = Bot(token=settings.LOGGER_BOT_TOKEN)
    app.state.logger_bot = logger_bot

    # Run polling in background
    app.state.polling_task = asyncio.create_task(
        dp.start_polling(
            bot, 
            cols=app.state.cols, 
            logger_bot=logger_bot,
            verb_service=app.state.verb_service
        )
    )


# async def close_telegram_bot(app: FastAPI):
#     # Retrieve bot from state
#     bot: Bot = app.state.bot
    
#     # Shutdown
#     print("Deleting webhook...")
#     await bot.delete_webhook()
#     await bot.session.close()


async def close_telegram_bot(app: FastAPI):
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
