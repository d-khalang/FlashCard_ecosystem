from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flashcard.api.routes import health
from flashcard.telegram import bot as bot_module

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

    monkeypatch.setattr(bot_module, "build_bot_dispatcher", lambda: (bot, dp))
    monkeypatch.setattr(bot_module, "Bot", lambda *args, **kwargs: logger_bot)
    monkeypatch.setattr(bot_module, "install_asyncio_exception_handler", lambda logger_bot: None)
    monkeypatch.setattr(
        bot_module,
        "init_and_get_mongo",
        AsyncMock(return_value=(InMemoryMongoClient(), object(), make_cols())),
    )
    monkeypatch.setattr(
        bot_module,
        "init_and_get_http_client",
        AsyncMock(return_value=FakeHTTPClient(FakeHTTPResponse(200, {}))),
    )

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
        ),
    )
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", fake_scheduler_loop)

    await bot_module.init_telegram_bot(app, bot_module.settings)

    assert app.state.bot is bot
    assert app.state.dispatcher is dp
    assert any(call.method == "SetWebhook" for call in bot_session.calls)
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

    monkeypatch.setattr(bot_module, "build_bot_dispatcher", lambda: (bot, dp))
    monkeypatch.setattr(bot_module, "Bot", lambda *args, **kwargs: logger_bot)
    monkeypatch.setattr(bot_module, "install_asyncio_exception_handler", lambda logger_bot: None)
    monkeypatch.setattr(
        bot_module,
        "init_and_get_mongo",
        AsyncMock(return_value=(InMemoryMongoClient(), object(), make_cols())),
    )
    monkeypatch.setattr(
        bot_module,
        "init_and_get_http_client",
        AsyncMock(return_value=FakeHTTPClient(FakeHTTPResponse(200, {}))),
    )
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", AsyncMock())
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
        ),
    )

    await bot_module.init_telegram_bot(app, bot_module.settings)

    assert any(call.method == "DeleteWebhook" for call in bot_session.calls)
    assert app.state.polling_task is not None
    await asyncio.sleep(0)
    assert polling_started.is_set()
    app.state.polling_task.cancel()


async def test_close_telegram_bot_closes_resources(monkeypatch):
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
    assert close_mongo.await_count == 1
    assert close_http.await_count == 1
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
