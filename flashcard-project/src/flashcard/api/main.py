# Init api
from typing import Optional

from fastapi import FastAPI
from flashcard.api.lifecycle.lifecycle import lifespan
from flashcard.api.routes import health, webhook
from flashcard.settings import Settings, get_setting
from flashcard.utils.logger import configure_log_level


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """
    Entry point for uvicorn (`factory=True`): loads settings unless given and builds the app.
    The lifespan and the webhook route read them from `app.state`, never from a global.
    """
    settings = settings or get_setting()
    configure_log_level(settings.LOG_LEVEL)
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.webhook_secret = settings.WEBHOOK_SECRET
    app.include_router(health.router)
    app.include_router(webhook.build_router(settings.WEBHOOK_PATH))
    return app
