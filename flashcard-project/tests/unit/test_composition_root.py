"""
Contract: one composition root (docs/bot-architecture-refactor.md, #10).

`flashcard/composition.py` is the only place that opens the shared clients and
builds services and use cases, so every runtime (FastAPI, dev polling, later the
Mini App) gets the same wiring. Telegram handlers receive use cases, not services.
"""
import ast
from pathlib import Path

import flashcard
from flashcard import composition
from flashcard.composition import build_core
from tests.helpers import TEST_LANGUAGE
from tests.integration.helpers import make_cols

SRC = Path(flashcard.__file__).parent
# One-off migrations open their own client and services (removed after the rollout).
MIGRATIONS = {"migrations/backfill_created_at.py", "migrations/backfill_current_review.py",
              "migrations/dedupe_expressions.py"}
BUILT_BY_THE_ROOT = {"ExpressionService", "UserService", "ConsumptionService", "ReviewStateStore",
                     "VerbService", "LLMService", "QuotaPolicy"}
OPENERS = {"init_and_get_mongo", "init_and_get_http_client"}
RAW_SERVICES = {"expression_service", "consumption_service", "review_state", "verb_service",
                "llm_service", "language_validator", "http_client"}


def _calls(names):
    for path in SRC.rglob("*.py"):
        module = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func).split(".")[-1]
                if called in names or (names is BUILT_BY_THE_ROOT and called.endswith("UseCases")):
                    yield module


def test_only_the_root_builds_services_and_use_cases():
    builders = set(_calls(BUILT_BY_THE_ROOT))
    assert builders <= {"composition.py"} | MIGRATIONS, builders - {"composition.py"} - MIGRATIONS


def test_only_the_root_opens_mongo_and_the_http_client():
    openers = set(_calls(OPENERS))
    assert openers <= {"composition.py"} | MIGRATIONS, openers - {"composition.py"} - MIGRATIONS


def test_handlers_take_use_cases_not_services():
    taking = {}
    for path in (SRC / "telegram" / "handlers").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = {a.arg for a in node.args.args + node.args.kwonlyargs} & RAW_SERVICES
                if args:
                    taking[f"{path.name}:{node.name}"] = args
    assert taking == {}


def test_handler_data_exposes_use_cases_and_no_raw_service(monkeypatch):
    monkeypatch.setattr(composition, "LLMService", lambda **_: object())
    monkeypatch.setattr(composition, "get_language_validator", lambda language: object())
    core = build_core(make_cols(), http_client=None, settings=object(), language=TEST_LANGUAGE)
    logger_bot = object()

    data = core.handler_data(logger_bot)

    assert set(data) == {
        "logger_bot", "language", "user_service",
        "review_use_cases", "creation_use_cases", "settings_use_cases",
        "story_use_cases", "verb_use_cases", "collection_use_cases",
    }
    assert data["logger_bot"] is logger_bot
    assert data["review_use_cases"] is core.review_use_cases
