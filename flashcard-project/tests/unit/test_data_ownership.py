"""
Contract: each collection is reachable only by its owners (docs/bot-architecture-refactor.md).

Services receive only their own collection, never the `cols` dict, so a service
cannot read or write another's data. `build_core` in the composition root is
the only place that hands collections out.

`users` field groups: profile/settings/onboarding/last_seen_at (UserService),
consumption (ConsumptionService), review state (ReviewStateStore).
"""
import ast
from pathlib import Path

import flashcard
from flashcard.settings import get_setting
from flashcard import composition
from flashcard.composition import build_core
from tests.integration.helpers import make_cols
from tests.helpers import TEST_LANGUAGE

SRC = Path(flashcard.__file__).parent
# Composition root, DB setup, and one-off migrations (removed after the rollout).
MAY_INDEX_COLS = {"composition.py", "db/mongo.py",
                  "migrations/backfill_created_at.py", "migrations/backfill_current_review.py",
                  "migrations/dedupe_expressions.py"}


def _modules():
    for path in SRC.rglob("*.py"):
        yield path.relative_to(SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def test_only_the_composition_root_indexes_cols():
    indexing = {name for name, tree in _modules() for node in ast.walk(tree)
                if isinstance(node, ast.Subscript) and ast.unparse(node.value).split(".")[-1] == "cols"}
    assert indexing <= MAY_INDEX_COLS, indexing - MAY_INDEX_COLS


def test_no_module_keeps_the_cols_dict():
    holders = {name for name, tree in _modules() for node in ast.walk(tree)
               if isinstance(node, ast.Attribute) and node.attr == "cols"
               and isinstance(node.value, ast.Name) and node.value.id == "self"}
    assert holders == set()


def test_each_service_gets_only_its_own_collection(monkeypatch):
    # The LLM client and language validator hold no collections; keep them (and the key file) out.
    monkeypatch.setattr(composition, "LLMService", lambda **_: object())
    monkeypatch.setattr(composition, "get_language_validator", lambda language: object())
    cols = make_cols()
    services = build_core(cols, http_client=None, settings=get_setting(), language=TEST_LANGUAGE)

    assert services.expression_service.expressions is cols["expression"]
    assert services.user_service.users is cols["users"]
    assert services.consumption_service.users is cols["users"]
    assert services.review_state.users is cols["users"]
    assert services.verb_service.conjugations is cols["conjugation"]
