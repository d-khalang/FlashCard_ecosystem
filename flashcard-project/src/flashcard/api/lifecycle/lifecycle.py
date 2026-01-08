from contextlib import asynccontextmanager
from fastapi import FastAPI
from flashcard.settings import settings
from flashcard.telegram.bot import init_telegram_bot, close_telegram_bot
from flashcard.db.mongo import init_mongo, close_mongo
from flashcard.services.http_client import init_http_client, close_http_client
from flashcard.services.verb import VerbService

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_mongo(app, settings)
    await init_http_client(app)
    
    # Initialize verb service business logic
    await init_telegram_bot(app, settings)

    try:
        yield
    finally:
        await close_telegram_bot(app)
        await close_mongo(app)
        await close_http_client(app)
