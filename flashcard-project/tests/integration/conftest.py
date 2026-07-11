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
from flashcard.telegram.bot import build_bot_dispatcher, build_dispatcher_data
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
def dispatcher_env(monkeypatch: pytest.MonkeyPatch, bot_and_session, llm_service, services, trace_logger):
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
    _, dp = build_bot_dispatcher()
    logger_bot, _ = make_bot()
    dispatcher_data = build_dispatcher_data(
        cols=services["expression_service"].cols,
        http_client=services["verb_service"].http_client,
        logger_bot=logger_bot,
        verb_service=services["verb_service"],
        expression_service=services["expression_service"],
        user_service=services["user_service"],
        consumption_service=services["consumption_service"],
        llm_service=llm_service,
        language_validator=BaseLanguageValidityChecker(),
    )
    yield {
        "bot": bot,
        "dp": dp,
        "session": session,
        "logger_bot": logger_bot,
        "dispatcher_data": dispatcher_data,
        "llm_service": llm_service,
        **services,
    }
