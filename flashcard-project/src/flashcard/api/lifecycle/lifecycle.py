from contextlib import asynccontextmanager
from fastapi import FastAPI
from flashcard.telegram.bot import running_bot

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings  # set by create_app
    async with running_bot(settings, settings.TELEGRAM_DELIVERY_MODE) as (resources, telegram):
        app.state.mongo_client = resources.mongo_client  # readiness check
        app.state.telegram = telegram  # webhook route
        yield
