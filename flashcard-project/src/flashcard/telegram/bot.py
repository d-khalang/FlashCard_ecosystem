import asyncio
import contextlib
from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from flashcard.settings import settings
from flashcard.telegram.handlers import messages, callbacks

# def build_bot_dispatcher() -> tuple[Bot, Dispatcher]:
#     bot = Bot(token=settings.BOT_TOKEN)
#     dp = Dispatcher()
    
#     # Include routers
#     dp.include_router(messages.router)
#     dp.include_router(callbacks.router)
    
#     return bot, dp

def build_bot_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    
    # Include routers
    dp.include_router(messages.router)
    dp.include_router(callbacks.router)

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

    # Run polling in background
    app.state.polling_task = asyncio.create_task(dp.start_polling(bot, cols=app.state.cols))


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
