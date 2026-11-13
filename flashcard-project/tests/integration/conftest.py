from __future__ import annotations

import pytest

from flashcard.services import trace_logger as trace_logger_module
from flashcard.services.language_validation import BaseLanguageValidityChecker
from flashcard.telegram.handlers import (
    collection,
    creation,
    errors,
    feedback,
    inline_remove,
    reply_commands,
    review,
    start,
    story,
    unknown,
    user_settings,
    verb,
)
from flashcard import composition
from flashcard.settings import get_setting
from flashcard.telegram.bot import build_bot_dispatcher
from .helpers import (
    DummyTraceLogger,
    FakeHTTPClient,
    FakeHTTPResponse,
    FakeLLMService,
    InMemoryMongoClient,
    make_bot,
    make_cols,
    make_services,
)
from tests.helpers import TEST_LANGUAGE


@pytest.fixture
def trace_logger(monkeypatch: pytest.MonkeyPatch) -> DummyTraceLogger:
    logger = DummyTraceLogger()
    monkeypatch.setattr(trace_logger_module, "get_trace_logger", lambda: logger)
    return logger


@pytest.fixture
def mongo_client() -> InMemoryMongoClient:
    return InMemoryMongoClient()


@pytest.fixture
def bot_and_session():
    return make_bot()


@pytest.fixture
def llm_service() -> FakeLLMService:
    return FakeLLMService()


@pytest.fixture
def fake_http_client() -> FakeHTTPClient:
    payload = {
        "success": True,
        "data": {
            "queried": "andare",
            "url": "http://scraper/conjugate?v=andare",
            "model": "andare",
            "principal_forms": {"infinito": "andare"},
            "auxiliary": "avere",
            "conjugations": {
                "indicativo": {
                    "presente": {
                        "io": "vado",
                        "tu": "vai",
                    }
                }
            },
        },
    }
    return FakeHTTPClient(FakeHTTPResponse(200, payload))


@pytest.fixture
def cols():
    return make_cols()


@pytest.fixture
def services(cols, fake_http_client):
    return make_services(cols, http_client=fake_http_client)


@pytest.fixture
def dispatcher_env(monkeypatch: pytest.MonkeyPatch, bot_and_session, llm_service, cols, fake_http_client, trace_logger):
    for module in [
        user_settings,
        feedback,
        reply_commands,
        start,
        review,
        verb,
        story,
        collection,
        inline_remove,
        unknown,
        creation,
        errors,
    ]:
        module.router._parent_router = None

    bot, session = bot_and_session
    _, dp = build_bot_dispatcher("123456:test-token", TEST_LANGUAGE)
    logger_bot, _ = make_bot()
    # The real composition root, with the LLM and validator swapped for test doubles.
    monkeypatch.setattr(composition, "LLMService", lambda **_: llm_service)
    monkeypatch.setattr(composition, "get_language_validator", lambda language: BaseLanguageValidityChecker())
    core = composition.build_core(cols, fake_http_client, get_setting(), TEST_LANGUAGE)
    yield {
        "bot": bot,
        "dp": dp,
        "session": session,
        "logger_bot": logger_bot,
        "dispatcher_data": core.handler_data(logger_bot, admin_id=0),
        "llm_service": llm_service,
        "cols": cols,  # for tests that seed or inspect the in-memory DB directly
        "expression_service": core.expression_service,
        "user_service": core.user_service,
        "consumption_service": core.consumption_service,
        "verb_service": core.verb_service,
        "review_state": core.review_state,
    }


# ---- Mini App: a real MongoDB ----------------------------------------------------------------------
import os
import uuid

from pymongo import AsyncMongoClient

from .study_helpers import FakeStudyLLM  # noqa: E402

TEST_MONGO_URI = os.environ.get("KARTINO_TEST_MONGO_URI", "mongodb://127.0.0.1:27019/?directConnection=true")


@pytest.fixture
async def mongo_cols():
    """Collections of a randomly named database on the dev MongoDB, dropped afterwards."""
    client = AsyncMongoClient(TEST_MONGO_URI, serverSelectionTimeoutMS=2000, tz_aware=True)
    try:
        await client.admin.command("ping")
    except Exception:
        await client.close()
        message = f"no MongoDB at {TEST_MONGO_URI} (set KARTINO_TEST_MONGO_URI)"
        if os.environ.get("KARTINO_REQUIRE_MONGO") == "1":
            pytest.fail(message)  # CI and releases: a missing database must not pass as a skip
        pytest.skip(message)
    name = f"kartino_test_{uuid.uuid4().hex}"
    db = client[name]
    cols = {"users": db["users"], "expression": db["expression"], "conjugation": db["conjugation"],
            "audio_words": db["audio_words"]}
    try:
        yield cols
    finally:
        await client.drop_database(name)
        await client.close()


@pytest.fixture
def study_llm() -> FakeStudyLLM:
    return FakeStudyLLM()


@pytest.fixture
async def study_core(monkeypatch: pytest.MonkeyPatch, mongo_cols, study_llm):
    """The real composition root over the real database, with the LLM and validator replaced."""
    monkeypatch.setattr(composition, "LLMService", lambda **_: study_llm)
    monkeypatch.setattr(composition, "get_language_validator", lambda language: BaseLanguageValidityChecker())
    core = composition.build_core(mongo_cols, None, get_setting(), TEST_LANGUAGE)
    await core.expression_service.ensure_indexes()
    await core.user_service.ensure_indexes()
    return core


# ---- Bot and Mini App together ---------------------------------------------------------------------
from contextlib import asynccontextmanager  # noqa: E402

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from flashcard.miniapp.api import create_app  # noqa: E402
from flashcard.miniapp.bot_buttons import BotCardButtons  # noqa: E402

from .harness import FakeSpeech, Harness  # noqa: E402

ROUTER_MODULES = [user_settings, feedback, reply_commands, start, review, verb, story, collection,
                  inline_remove, unknown, creation, errors]


@asynccontextmanager
async def open_harness(monkeypatch: pytest.MonkeyPatch, cols, llm, http_client, *, static_dir: str | None = None):
    """
    The real bot dispatcher and the real Mini App API sharing one database and one fake Telegram.
    With `static_dir`, the API also serves that frontend build, as in production.
    """
    for module in ROUTER_MODULES:
        module.router._parent_router = None  # the routers are module-global
    speech = FakeSpeech()
    monkeypatch.setattr(composition, "LLMService", lambda **_: llm)
    monkeypatch.setattr(composition, "get_language_validator", lambda language: BaseLanguageValidityChecker())
    monkeypatch.setattr(composition, "EdgeSpeechProvider", lambda: speech)
    settings = get_setting()
    if static_dir is not None:
        settings = settings.model_copy(update={"MINIAPP_STATIC_DIR": static_dir})
    core = composition.build_core(cols, http_client, settings, TEST_LANGUAGE)
    await core.expression_service.ensure_indexes()
    await core.user_service.ensure_indexes()

    bot, session = make_bot()
    _, dp = build_bot_dispatcher("123456:test-token", TEST_LANGUAGE)
    logger_bot, _ = make_bot()
    app = create_app(settings)
    app.state.core = core
    app.state.bot_buttons = BotCardButtons(bot)  # the app edits bot messages through the same fake
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield Harness(bot=bot, session=session, dp=dp, handler_data=core.handler_data(logger_bot, admin_id=0),
                          app=app, api=client, cols=cols, llm=llm, speech=speech)
        finally:
            await app.state.prepared.close()
            await app.state.bot_buttons.close()


@pytest.fixture
async def harness(monkeypatch: pytest.MonkeyPatch, mongo_cols, study_llm, fake_http_client, trace_logger):
    async with open_harness(monkeypatch, mongo_cols, study_llm, fake_http_client) as opened:
        yield opened
