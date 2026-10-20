from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flashcard.api.routes import health
from flashcard.telegram import bot as bot_module
from tests.helpers import TEST_LANGUAGE

from .helpers import (
    DummyTraceLogger,
    FakeHTTPClient,
    FakeHTTPResponse,
    InMemoryMongoClient,
    make_bot,
    make_cols,
)


async def test_init_telegram_bot_webhook_mode_sets_webhook(monkeypatch):
    app = FastAPI()
    bot, bot_session = make_bot()
    logger_bot, _ = make_bot()
    dp = SimpleNamespace(resolve_used_update_types=lambda: ["message"], start_polling=AsyncMock())
    scheduler_started = asyncio.Event()

    monkeypatch.setattr(bot_module, "build_bot_dispatcher", lambda language: (bot, dp))
    monkeypatch.setattr(bot_module.LanguageConfig, "from_settings", lambda settings: TEST_LANGUAGE)
    monkeypatch.setattr(bot_module, "Bot", lambda *args, **kwargs: logger_bot)
    monkeypatch.setattr(bot_module, "install_asyncio_exception_handler", lambda logger_bot: None)
    # The lifespan has already opened Mongo and the HTTP client; the bot must only use them.
    app.state.cols = make_cols()
    app.state.http_client = FakeHTTPClient(FakeHTTPResponse(200, {}))
    open_mongo, open_http = AsyncMock(), AsyncMock()
    monkeypatch.setattr(bot_module, "init_and_get_mongo", open_mongo)
    monkeypatch.setattr(bot_module, "init_and_get_http_client", open_http)

    async def fake_scheduler_loop(**kwargs):
        scheduler_started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(bot_module, "get_trace_logger", lambda: DummyTraceLogger())
    monkeypatch.setattr(
        bot_module,
        "settings",
        SimpleNamespace(
            BOT_TOKEN="123:TEST",
            LOGGER_BOT_TOKEN="456:TEST",
            TELEGRAM_DELIVERY_MODE="webhook",
            WEBHOOK_SECRET="secret",
            webhook_url="https://bot.example.com/webhook",
            ADMIN_ID=1,
            REVIEW_PAUSE_RULE="legacy",
        ),
    )
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", fake_scheduler_loop)
    monkeypatch.setattr(bot_module, "LLMService", lambda **_: object())

    await bot_module.init_telegram_bot(app, bot_module.settings)

    assert app.state.bot is bot
    assert app.state.dispatcher is dp
    assert any(call.method == "SetWebhook" for call in bot_session.calls)
    open_mongo.assert_not_awaited()
    open_http.assert_not_awaited()
    await asyncio.sleep(0)
    assert app.state.scheduler_task is not None
    assert scheduler_started.is_set()
    app.state.scheduler_task.cancel()


async def test_init_telegram_bot_polling_mode_deletes_webhook_and_starts_polling(monkeypatch):
    app = FastAPI()
    bot, bot_session = make_bot()
    logger_bot, _ = make_bot()
    polling_started = asyncio.Event()

    async def fake_start_polling(*args, **kwargs):
        polling_started.set()
        await asyncio.sleep(3600)

    dp = SimpleNamespace(resolve_used_update_types=lambda: ["message", "callback_query"], start_polling=fake_start_polling)

    monkeypatch.setattr(bot_module, "build_bot_dispatcher", lambda language: (bot, dp))
    monkeypatch.setattr(bot_module.LanguageConfig, "from_settings", lambda settings: TEST_LANGUAGE)
    monkeypatch.setattr(bot_module, "Bot", lambda *args, **kwargs: logger_bot)
    monkeypatch.setattr(bot_module, "install_asyncio_exception_handler", lambda logger_bot: None)
    # The lifespan has already opened Mongo and the HTTP client; the bot must only use them.
    app.state.cols = make_cols()
    app.state.http_client = FakeHTTPClient(FakeHTTPResponse(200, {}))
    open_mongo, open_http = AsyncMock(), AsyncMock()
    monkeypatch.setattr(bot_module, "init_and_get_mongo", open_mongo)
    monkeypatch.setattr(bot_module, "init_and_get_http_client", open_http)
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", AsyncMock())
    monkeypatch.setattr(bot_module, "LLMService", lambda **_: object())
    monkeypatch.setattr(bot_module, "get_trace_logger", lambda: DummyTraceLogger())
    monkeypatch.setattr(
        bot_module,
        "settings",
        SimpleNamespace(
            BOT_TOKEN="123:TEST",
            LOGGER_BOT_TOKEN="456:TEST",
            TELEGRAM_DELIVERY_MODE="polling",
            WEBHOOK_SECRET="secret",
            webhook_url="https://bot.example.com/webhook",
            ADMIN_ID=1,
            REVIEW_PAUSE_RULE="legacy",
        ),
    )

    await bot_module.init_telegram_bot(app, bot_module.settings)

    assert any(call.method == "DeleteWebhook" for call in bot_session.calls)
    open_mongo.assert_not_awaited()
    open_http.assert_not_awaited()
    assert app.state.polling_task is not None
    await asyncio.sleep(0)
    assert polling_started.is_set()
    app.state.polling_task.cancel()


async def test_close_telegram_bot_stops_the_bot_but_leaves_the_lifespans_clients(monkeypatch):
    app = FastAPI()
    bot, _ = make_bot()
    logger_bot, _ = make_bot()
    scheduler_task = asyncio.create_task(asyncio.sleep(3600))
    polling_task = asyncio.create_task(asyncio.sleep(3600))
    mongo_client = object()
    http_client = object()
    trace_logger = DummyTraceLogger()

    app.state.bot = bot
    app.state.logger_bot = logger_bot
    app.state.scheduler_task = scheduler_task
    app.state.polling_task = polling_task
    app.state.mongo_client = mongo_client
    app.state.http_client = http_client

    close_mongo = AsyncMock()
    close_http = AsyncMock()
    monkeypatch.setattr(bot_module, "close_mongo_on_client", close_mongo)
    monkeypatch.setattr(bot_module, "close_http_client_on_client", close_http)
    monkeypatch.setattr(bot_module, "get_trace_logger", lambda: trace_logger)
    monkeypatch.setattr(
        bot_module,
        "settings",
        SimpleNamespace(TELEGRAM_DELIVERY_MODE="webhook"),
    )

    await bot_module.close_telegram_bot(app)

    assert scheduler_task.cancelled()
    assert polling_task.cancelled()
    # The lifespan opened Mongo and the HTTP client, so it closes them, not the bot.
    close_mongo.assert_not_awaited()
    close_http.assert_not_awaited()
    assert trace_logger.shutdown_called is True


def test_health_routes_report_liveness_and_readiness(monkeypatch):
    health_app = FastAPI()
    health_app.include_router(health.router)
    health_app.state.mongo_client = InMemoryMongoClient()

    with TestClient(health_app) as client:
        live = client.get("/health")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_readiness_returns_503_when_mongo_ping_fails(monkeypatch):
    health_app = FastAPI()
    health_app.include_router(health.router)
    health_app.state.mongo_client = InMemoryMongoClient(should_fail=True)

    with TestClient(health_app) as client:
        ready = client.get("/health/ready")

    assert ready.status_code == 503
    assert ready.json()["reason"] == "database unreachable"


async def test_lifespan_opens_one_mongo_and_one_http_client_and_closes_each_once(monkeypatch):
    """Before, the bot opened a second pair: the first was never closed, the second twice."""
    from flashcard.api.lifecycle import lifecycle
    from flashcard.db import mongo as mongo_module
    from flashcard.services import http_client as http_module

    opened = {"mongo": [], "http": []}

    class FakeMongoClient:
        def __init__(self, *args, **kwargs):
            self.closes = 0
            opened["mongo"].append(self)

        def __getitem__(self, name):
            return _FakeDB()

        async def close(self):
            self.closes += 1

    class _FakeDB:
        def __getitem__(self, name):
            return object()

    class FakeHTTPXClient:
        def __init__(self, *args, **kwargs):
            self.closes = 0
            opened["http"].append(self)

        async def aclose(self):
            self.closes += 1

    bot, _ = make_bot()
    logger_bot, _ = make_bot()

    async def fake_start_polling(*args, **kwargs):
        await asyncio.sleep(3600)

    dp = SimpleNamespace(resolve_used_update_types=lambda: ["message"], start_polling=fake_start_polling)
    monkeypatch.setattr(mongo_module, "AsyncMongoClient", FakeMongoClient)
    monkeypatch.setattr(http_module.httpx, "AsyncClient", FakeHTTPXClient)
    monkeypatch.setattr(bot_module, "build_bot_dispatcher", lambda language: (bot, dp))
    monkeypatch.setattr(bot_module.LanguageConfig, "from_settings", lambda settings: TEST_LANGUAGE)
    monkeypatch.setattr(bot_module, "Bot", lambda *args, **kwargs: logger_bot)
    monkeypatch.setattr(bot_module, "install_asyncio_exception_handler", lambda logger_bot: None)
    monkeypatch.setattr(bot_module, "LLMService", lambda **_: object())
    monkeypatch.setattr(bot_module, "get_trace_logger", lambda: DummyTraceLogger())
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", AsyncMock())

    app = FastAPI()
    async with lifecycle.lifespan(app):
        assert len(opened["mongo"]) == 1 and len(opened["http"]) == 1
        # The bot and the readiness check use the lifespan's clients.
        assert app.state.mongo_client is opened["mongo"][0]
        assert app.state.http_client is opened["http"][0]

    assert [client.closes for client in opened["mongo"]] == [1]
    assert [client.closes for client in opened["http"]] == [1]
