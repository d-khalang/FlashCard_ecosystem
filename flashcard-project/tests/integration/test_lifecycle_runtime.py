from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flashcard import composition
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


def _settings(**overrides):
    return SimpleNamespace(
        LOGGER_BOT_TOKEN="456:TEST",
        WEBHOOK_SECRET="secret",
        webhook_url="https://bot.example.com/webhook",
        ADMIN_ID=1,
        REVIEW_PAUSE_RULE="legacy",
        **overrides,
    )


def _core():
    return SimpleNamespace(
        language=TEST_LANGUAGE,
        user_service=object(),
        review_use_cases=object(),
        handler_data=lambda logger_bot: {"logger_bot": logger_bot, "x": 1},
    )


def _patch_bots(monkeypatch, bot, logger_bot, dp):
    monkeypatch.setattr(bot_module, "build_bot_dispatcher", lambda language: (bot, dp))
    monkeypatch.setattr(bot_module, "Bot", lambda *args, **kwargs: logger_bot)
    monkeypatch.setattr(bot_module, "install_asyncio_exception_handler", lambda logger_bot: None)


async def test_start_telegram_webhook_mode_sets_webhook_and_starts_the_scheduler(monkeypatch):
    bot, bot_session = make_bot()
    logger_bot, _ = make_bot()
    dp = SimpleNamespace(resolve_used_update_types=lambda: ["message"], start_polling=AsyncMock())
    scheduler_started = asyncio.Event()

    async def fake_scheduler_loop(**kwargs):
        scheduler_started.set()
        await asyncio.sleep(3600)

    _patch_bots(monkeypatch, bot, logger_bot, dp)
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", fake_scheduler_loop)

    runtime = await bot_module.start_telegram(_core(), _settings(), "webhook")

    assert runtime.bot is bot and runtime.dispatcher is dp and runtime.logger_bot is logger_bot
    assert runtime.handler_data == {"logger_bot": logger_bot, "x": 1}
    assert any(call.method == "SetWebhook" for call in bot_session.calls)
    assert runtime.polling_task is None
    dp.start_polling.assert_not_called()
    await asyncio.sleep(0)
    assert scheduler_started.is_set()
    runtime.scheduler_task.cancel()


async def test_start_telegram_polling_mode_deletes_webhook_and_polls_with_the_handler_data(monkeypatch):
    bot, bot_session = make_bot()
    logger_bot, _ = make_bot()
    polling_kwargs = {}

    async def fake_start_polling(*args, **kwargs):
        polling_kwargs.update(kwargs)
        await asyncio.sleep(3600)

    dp = SimpleNamespace(resolve_used_update_types=lambda: ["message", "callback_query"], start_polling=fake_start_polling)
    _patch_bots(monkeypatch, bot, logger_bot, dp)
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", AsyncMock())

    runtime = await bot_module.start_telegram(_core(), _settings(), "polling")

    assert any(call.method == "DeleteWebhook" for call in bot_session.calls)
    await asyncio.sleep(0)
    assert polling_kwargs == {"allowed_updates": ["message", "callback_query"], "logger_bot": logger_bot, "x": 1}
    runtime.polling_task.cancel()
    runtime.scheduler_task.cancel()


async def test_stop_telegram_cancels_tasks_removes_the_webhook_and_closes_both_bots(monkeypatch):
    bot, bot_session = make_bot()
    logger_bot, _ = make_bot()
    bot.session.close = AsyncMock()
    logger_bot.session.close = AsyncMock()
    trace_logger = DummyTraceLogger()
    monkeypatch.setattr(bot_module, "get_trace_logger", lambda: trace_logger)
    runtime = bot_module.TelegramRuntime(
        bot=bot, logger_bot=logger_bot, dispatcher=None, handler_data={}, mode="webhook",
        polling_task=asyncio.create_task(asyncio.sleep(3600)),
        scheduler_task=asyncio.create_task(asyncio.sleep(3600)),
    )

    await bot_module.stop_telegram(runtime)

    assert runtime.scheduler_task.cancelled()
    assert runtime.polling_task.cancelled()
    assert any(call.method == "DeleteWebhook" for call in bot_session.calls)
    bot.session.close.assert_awaited_once()
    logger_bot.session.close.assert_awaited_once()
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
    monkeypatch.setattr(composition, "LLMService", lambda **_: object())
    monkeypatch.setattr(bot_module, "get_trace_logger", lambda: DummyTraceLogger())
    monkeypatch.setattr("flashcard.scheduler.scheduler.scheduler_loop", AsyncMock())

    app = FastAPI()
    async with lifecycle.lifespan(app):
        assert len(opened["mongo"]) == 1 and len(opened["http"]) == 1
        # The readiness check uses the same Mongo client; the webhook route gets the runtime.
        assert app.state.mongo_client is opened["mongo"][0]
        assert app.state.telegram.bot is bot
        assert app.state.telegram.handler_data["verb_use_cases"].verbs.http_client is opened["http"][0]

    assert [client.closes for client in opened["mongo"]] == [1]
    assert [client.closes for client in opened["http"]] == [1]


async def test_running_bot_closes_the_clients_when_telegram_fails_to_start(monkeypatch):
    """A failed start (e.g. Telegram unreachable) must not leak the Mongo and HTTP clients."""
    closed = []
    resources = composition.Resources(mongo_client=object(), cols=make_cols(), http_client=object())
    monkeypatch.setattr(bot_module.LanguageConfig, "from_settings", lambda settings: TEST_LANGUAGE)
    monkeypatch.setattr(composition, "init_and_get_mongo", AsyncMock(return_value=(resources.mongo_client, None, resources.cols)))
    monkeypatch.setattr(composition, "init_and_get_http_client", AsyncMock(return_value=resources.http_client))
    monkeypatch.setattr(composition, "close_mongo_on_client", AsyncMock(side_effect=lambda c: closed.append("mongo")))
    monkeypatch.setattr(composition, "close_http_client_on_client", AsyncMock(side_effect=lambda c: closed.append("http")))
    monkeypatch.setattr(composition, "LLMService", lambda **_: object())
    monkeypatch.setattr(bot_module, "start_telegram", AsyncMock(side_effect=RuntimeError("telegram down")))

    with pytest.raises(RuntimeError, match="telegram down"):
        async with bot_module.running_bot(_settings(), "polling"):
            pass

    assert closed == ["http", "mongo"]
