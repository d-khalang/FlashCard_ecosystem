"""
The Verbs page's shared fixtures (docs/verbs/fixtures, owned by the coordinator; never edit them
here) and a fake conjugator v2 that answers from them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.integration.helpers import FakeHTTPClient, FakeHTTPResponse

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "verbs" / "fixtures"

# What the fake /v2/infinitives knows: infinitives only (contract section 3).
KNOWN_INFINITIVES = {"andare", "andarsene", "prendere", "svegliarsi", "essere", "fare", "potere", "uscire"}


def load(name: str) -> Any:
    """A fixture by its path under docs/verbs/fixtures, e.g. "conjugator/conjugate-vado.json"."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_names(folder: str) -> list[str]:
    return sorted(f"{folder}/{path.name}" for path in (FIXTURES / folder).glob("*.json"))


def andare_answer(query: str) -> dict:
    """GET /v2/conjugate for a query that belongs to andare: the fixture verb, with a fitting match."""
    answer = load("conjugator/conjugate-vado.json")
    if query == "vado":
        return answer
    if query == "andre":
        return load("conjugator/conjugate-fuzzy.json")
    answer["match"] = {"query": query, "kind": "infinitive", "slots": [], "candidates": []}
    return answer


def fake_conjugator(*, broken: bool = False) -> FakeHTTPClient:
    """
    A conjugator v2 over the fixtures: "andare", "vado" and "andre" find andare; any other query is
    the not-found fixture. `broken`: every route answers 500.
    """
    if broken:
        return FakeHTTPClient(FakeHTTPResponse(500, {"detail": "boom"}))

    def conjugate(params: dict) -> FakeHTTPResponse:
        if params.get("q") in ("andare", "vado", "andre"):
            return FakeHTTPResponse(200, andare_answer(params["q"]))
        return FakeHTTPResponse(404, load("conjugator/conjugate-not-found.json"))

    def suggest(params: dict) -> FakeHTTPResponse:
        prefix = params.get("q", "")
        items = [] if len(prefix) < 2 else [v for v in load("conjugator/suggest-and.json")["items"] if v.startswith(prefix)]
        return FakeHTTPResponse(200, {"items": items})

    def infinitives(body: dict) -> FakeHTTPResponse:
        words = body["words"]
        assert len(words) <= 500
        return FakeHTTPResponse(200, {"infinitives": {w: (w if w in KNOWN_INFINITIVES else None) for w in words}})

    return FakeHTTPClient({"/v2/conjugate": conjugate, "/v2/suggest": suggest, "/v2/infinitives": infinitives})


def same_shape(actual: Any, expected: Any, path: str = "$") -> list[str]:
    """
    Differences in keys and JSON types between a response and a fixture (values may differ).
    Lists of the same length are compared item by item (items may be of a union type, e.g. simple and
    compound parts); otherwise every item of `actual` is compared with the first item of `expected`.
    A null on either side matches anything: the fixture shows one case of an optional field.
    """
    if actual is None or expected is None:
        return []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected an object, got {type(actual).__name__}"]
        problems = []
        if set(actual) != set(expected):
            problems.append(f"{path}: keys {sorted(actual)} != {sorted(expected)}")
        for key in set(actual) & set(expected):
            problems += same_shape(actual[key], expected[key], f"{path}.{key}")
        return problems
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected a list, got {type(actual).__name__}"]
        if not expected:
            return []
        problems = []
        for index, item in enumerate(actual):
            model = expected[index] if len(actual) == len(expected) else expected[0]
            problems += same_shape(item, model, f"{path}[{index}]")
        return problems
    kinds = (bool, int, float, str)
    expected_kind = next(k for k in kinds if isinstance(expected, k))
    if type(actual) is not expected_kind and not (expected_kind is float and type(actual) is int):
        return [f"{path}: {type(actual).__name__} != {expected_kind.__name__}"]
    return []

