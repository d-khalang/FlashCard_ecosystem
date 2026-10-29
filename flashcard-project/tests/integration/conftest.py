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
from flashcard.settings import settings
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
    _, dp = build_bot_dispatcher(TEST_LANGUAGE)
    logger_bot, _ = make_bot()
    # The real composition root, with the LLM and validator swapped for test doubles.
    monkeypatch.setattr(composition, "LLMService", lambda **_: llm_service)
    monkeypatch.setattr(composition, "get_language_validator", lambda language: BaseLanguageValidityChecker())
    core = composition.build_core(cols, fake_http_client, settings, TEST_LANGUAGE)
    yield {
        "bot": bot,
        "dp": dp,
        "session": session,
        "logger_bot": logger_bot,
        "dispatcher_data": core.handler_data(logger_bot),
        "llm_service": llm_service,
        "cols": cols,  # for tests that seed or inspect the in-memory DB directly
        "expression_service": core.expression_service,
        "user_service": core.user_service,
        "consumption_service": core.consumption_service,
        "verb_service": core.verb_service,
        "review_state": core.review_state,
    }
