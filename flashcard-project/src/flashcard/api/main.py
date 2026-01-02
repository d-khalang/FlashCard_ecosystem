from fastapi import FastAPI
from flashcard.api.lifecycle.lifecycle import lifespan
from flashcard.api.routes import health, webhook

app = FastAPI(lifespan=lifespan)

app.include_router(health.router)
app.include_router(webhook.router)
