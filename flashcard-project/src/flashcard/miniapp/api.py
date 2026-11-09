"""
The Mini App's HTTP app: FastAPI + the shared core. No Telegram polling, webhook or scheduler.

Entry point: `flashcard-miniapp` (uvicorn, factory=True). Serves the built frontend from
MINIAPP_STATIC_DIR when set.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from aiogram import Bot
from fastapi import APIRouter, FastAPI
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from flashcard.api.routes import health
from flashcard.composition import build_core, open_resources
from flashcard.language import LanguageConfig
from flashcard.miniapp.bot_buttons import BotCardButtons
from flashcard.miniapp.errors import install_error_handlers
from flashcard.miniapp.prefetch import PreparedCards
from flashcard.miniapp.rate_limit import DailyBudget, RateLimiter
from flashcard.miniapp.routes import audio, cards, collection, me, settings as settings_routes, study
from flashcard.settings import Settings, get_setting
from flashcard.telegram.session import build_ipv4_session
from flashcard.utils.logger import configure_log_level

API_PREFIX = "/api/v1"
# Bodies are small JSON; nothing legitimate comes close.
MAX_BODY_BYTES = 64 * 1024
# Per user and minute: the routes that call the LLM, and all others.
LLM_LIMIT_PER_MINUTE = 20
GENERAL_LIMIT_PER_MINUTE = 120
# Per user and minute: generated audio clips. A stored word replayed is not charged.
AUDIO_LIMIT_PER_MINUTE = 30

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://telegram.org",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    # Card audio is fetched with sign-in and played from a blob; data: is the clip that unlocks playback.
    "media-src 'self' blob: data:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors https://web.telegram.org https://*.telegram.org",
])


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    async with open_resources(settings) as resources:
        app.state.core = build_core(
            resources.cols, resources.http_client, settings, LanguageConfig.from_settings(settings))
        app.state.mongo_client = resources.mongo_client  # readiness check
        try:
            yield
        finally:
            await app.state.prepared.close()
            await app.state.bot_buttons.close()


class SecurityHeaders:
    """Adds the CSP and nosniff to every response; API responses are never cached."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                headers["X-Content-Type-Options"] = "nosniff"
                if (path.startswith(API_PREFIX) or path.startswith("/health")) and "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimit:
    """
    Refuses request bodies over `limit` bytes with 413, before sign-in and for every route: by
    Content-Length when it is honest, and while streaming when it is missing or wrong.
    """

    def __init__(self, app, limit: int = MAX_BODY_BYTES):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            await self._refuse(send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    # An HTTPException passes FastAPI's body reading (any other error there is a 400)
                    # and reaches the error handlers, which answer 413 in the usual JSON shape.
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _refuse(send):
        body = json.dumps({"error": {"code": "payload_too_large", "message": "The request is too large."}}).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


class FrontendFiles(StaticFiles):
    """
    The built frontend. Never answers for /api (a missing API route stays the API's JSON 404),
    never caches index.html, caches the fingerprinted assets for good, and serves index.html for
    paths that look like app routes (no file extension), so a reload on one works.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (scope["path"] == "/api" or scope["path"].startswith("/api/")):
            raise HTTPException(status_code=404)
        await super().__call__(scope, receive, send)

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or "." in Path(path).name:
                raise
            response = await super().get_response("index.html", scope)
        if str(getattr(response, "path", "")).endswith("index.html"):
            response.headers["Cache-Control"] = "no-cache"
        elif Path(path).parts[:1] == ("assets",) and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Entry point for uvicorn (`factory=True`): loads settings unless given and builds the app."""
    settings = settings or get_setting()
    configure_log_level(settings.LOG_LEVEL)
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.limiters = {
        "llm": RateLimiter(LLM_LIMIT_PER_MINUTE),
        "general": RateLimiter(GENERAL_LIMIT_PER_MINUTE),
        "audio": RateLimiter(AUDIO_LIMIT_PER_MINUTE),
    }
    app.state.budget = DailyBudget(settings.MINIAPP_LLM_DAILY_ATTEMPTS)
    app.state.prepared = PreparedCards()
    # Connects on first use, not here.
    app.state.bot_buttons = BotCardButtons(Bot(token=settings.BOT_TOKEN, session=build_ipv4_session()))
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    for module in (me, study, cards, collection, audio, settings_routes):
        api.include_router(module.router)
    api.include_router(health.router)
    app.include_router(api)
    app.include_router(health.router)

    # Last, so that no file can shadow a route above.
    if settings.MINIAPP_STATIC_DIR:
        app.mount("/", FrontendFiles(directory=settings.MINIAPP_STATIC_DIR, html=True), name="frontend")

    app.add_middleware(BodyLimit)
    app.add_middleware(SecurityHeaders)
    return app


def main() -> None:
    """Production entry point (`flashcard-miniapp`)."""
    uvicorn.run(
        "flashcard.miniapp.api:create_app",
        factory=True,
        host="0.0.0.0",
        port=get_setting().PORT,
        reload=False,
    )
