"""
Live contract tests: the real outside services the bot depends on, called through the bot's own
clients. They catch what mocks cannot: a changed model, API or voice, a broken key, a quota.

- Groq (LLM): needs KARTINO_CONTRACT_GROQ_KEY. Uses the production model setting.
- Microsoft edge-tts (speech): no key.
- it-conjugator: the API from ../it-conjugator-api (its submodule must be checked out), started
  locally and called through VerbService.

They cost a few LLM calls and need the internet, so they run only when asked:
`KARTINO_CONTRACT=1 pytest tests/contract`. A missing key or submodule then skips; with
KARTINO_REQUIRE_CONTRACT=1 (the release workflow, for a release candidate) it fails instead.
Nothing here prints a key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

CONJUGATOR_DIR = Path(__file__).resolve().parents[3] / "it-conjugator-api"


def enabled() -> bool:
    return "1" in (os.environ.get("KARTINO_CONTRACT"), os.environ.get("KARTINO_REQUIRE_CONTRACT"))


@pytest.fixture(autouse=True)
def only_when_asked():
    if not enabled():
        pytest.skip("live contract tests run only with KARTINO_CONTRACT=1")


def missing(reason: str):
    if os.environ.get("KARTINO_REQUIRE_CONTRACT") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def groq_key_file(tmp_path_factory) -> str:
    key = os.environ.get("KARTINO_CONTRACT_GROQ_KEY", "").split()
    if not key:
        missing("no KARTINO_CONTRACT_GROQ_KEY")
    path = tmp_path_factory.mktemp("llm") / "llm_key.json"
    path.write_text(json.dumps({"core": [{"name": "contract", "api_key": key[0], "provider": "groq"}],
                                "reminder": [], "users": {}}), encoding="utf-8")
    return str(path)
