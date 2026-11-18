"""
The Verbs page routes (docs/verbs/contract.md section 4) through the real composition root, over the
in-memory database and a fake conjugator v2. Every answer has the keys and types of its Mini App fixture.
"""
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from bson import ObjectId
from httpx import ASGITransport

from flashcard import composition
from flashcard.miniapp.api import create_app
from flashcard.schemas.user import stored_user_id
from flashcard.settings import get_setting
from tests.helpers import TEST_LANGUAGE
from tests.integration.helpers import make_cols
from tests.integration.study_helpers import auth_header
from tests.verb_fixtures import fake_conjugator, load, same_shape

USER = 42


@pytest.fixture
def env(monkeypatch):
    def build(*, http=None, language=TEST_LANGUAGE):
        monkeypatch.setattr(composition, "LLMService", lambda **_: object())
        monkeypatch.setattr(composition, "get_language_validator", lambda language: object())
        cols = make_cols()
        settings = get_setting().model_copy(update={"SCRAPER_URL": "http://conjugator", "SCRAPER_PORT": 8080})
        app = create_app(settings)
        app.state.core = composition.build_core(cols, http or fake_conjugator(), settings, language)
        client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        return app, cols, client
    return build


async def _get(client, path):
    return await client.get(f"/api/v1/verbs{path}", headers=auth_header(USER))


def _shape(response, fixture):
    assert same_shape(response.json(), load(fixture)) == []


def _seed_cards(cols, *values_meanings):
    for value, meaning in values_meanings:
        cols["expression"].docs.append({
            "_id": ObjectId(), "user_id": stored_user_id(USER), "value": value, "status": "active",
            "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
            "last_card": {"card": {"translations": [{"label": "🇬🇧 EN", "text": meaning}]}}})


class TestLookup:

    async def test_found(self, env):
        _, cols, client = env()
        _seed_cards(cols, ("andare", "to go"))
        async with client:
            response = await _get(client, "/lookup?q=vado")

        assert response.status_code == 200
        _shape(response, "miniapp/lookup-vado.json")
        body = response.json()
        expected = load("miniapp/lookup-vado.json")
        assert body["verb"] == expected["verb"] and body["match"] == expected["match"]
        assert (body["meaning"], body["in_collection"]) == ("to go", True)
        assert set(body["level_tenses"]) == set(expected["level_tenses"])

    async def test_not_found(self, env):
        _, _, client = env()
        async with client:
            response = await _get(client, "/lookup?q=qwerty")

        _shape(response, "miniapp/lookup-not-found.json")
        assert response.json() == load("miniapp/lookup-not-found.json")

    @pytest.mark.parametrize("q", ["123", "", "a b c d e"])
    async def test_invalid(self, env, q):
        _, _, client = env()
        async with client:
            response = await _get(client, f"/lookup?q={q}")

        _shape(response, "miniapp/lookup-invalid.json")
        assert response.json() == {"status": "invalid", "query": q}

    async def test_conjugator_down_is_503_in_the_error_shape(self, env):
        _, _, client = env(http=fake_conjugator(broken=True))
        async with client:
            response = await _get(client, "/lookup?q=vado")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"


class TestHomeAndSuggest:

    async def test_home(self, env):
        _, cols, client = env()
        _seed_cards(cols, ("prendere", "to take"), ("letto", "bed"), ("svegliarsi", "to wake up"))
        async with client:
            await _get(client, "/lookup?q=andare")
            response = await _get(client, "/home")

        _shape(response, "miniapp/home.json")
        body = response.json()
        assert body["recent"] == ["andare"]
        assert [c["infinitive"] for c in body["collection"]] == ["svegliarsi", "prendere"]  # newest first

    async def test_suggest(self, env):
        _, _, client = env()
        async with client:
            response = await _get(client, "/suggest?q=and")

        _shape(response, "miniapp/suggest-and.json")  # the fixture shows the shape, not the list

    async def test_suggest_has_its_own_limit_and_writes_nothing(self, env):
        app, cols, client = env()
        app.state.limiters["suggest"].limit = 2
        async with client:
            codes = [(await _get(client, "/suggest?q=and")).status_code for _ in range(3)]
            home = await _get(client, "/home")

        assert codes == [200, 200, 429]
        assert home.status_code == 200  # the general limit is untouched
        assert app.state.limiters["general"].hit(USER) == 0
        assert len(cols["users"].docs) == 1  # created by /home, not by suggest


class TestDrill:

    @pytest.mark.parametrize("tense_id, fixture", [
        ("indicativo-futuro_semplice", "miniapp/drill-andare-futuro_semplice.json"),
        ("indicativo-passato_prossimo", "miniapp/drill-andare-passato_prossimo.json"),
    ])
    async def test_drill_is_the_fixture(self, env, tense_id, fixture):
        _, _, client = env()
        async with client:
            response = await _get(client, f"/andare/drill/{tense_id}")

        assert response.status_code == 200
        _shape(response, fixture)
        assert response.json() == load(fixture)

    async def test_irregular_form_hint_has_no_stem(self, env):
        _, _, client = env()
        async with client:
            response = await _get(client, "/andare/drill/imperativo-presente")

        hints = [item["hint"] for item in response.json()["items"]]
        assert {"kind": "irregular_stem", "stem": "vad"} in hints
        assert all(h is None or set(h) in ({"kind", "stem"}, {"kind"}) for h in hints)

    @pytest.mark.parametrize("path", ["/qwerty/drill/indicativo-presente", "/andare/drill/nope",
                                      "/vado/drill/indicativo-presente"])
    async def test_unknown_verb_or_tense_is_404(self, env, path):
        _, _, client = env()
        async with client:
            response = await _get(client, path)

        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


class TestPractice:

    async def test_practice_is_stored(self, env):
        _, cols, client = env()
        async with client:
            response = await client.post("/api/v1/verbs/practice", json=load("miniapp/practice-request.json"),
                                         headers=auth_header(USER))

        assert response.status_code == 204 and response.content == b""
        [doc] = cols["verb_practice"].docs
        assert doc["tenses"]["indicativo-futuro_semplice"]["missed"] == ["1p", "2p"]

    @pytest.mark.parametrize("change", [{"score": 9}, {"tense_id": "nope"}, {"missed": ["7x"]}, {"extra": 1},
                                        {"score": "4"}, {"score": 5, "out_of": 4}])
    async def test_invalid_body_is_422(self, env, change):
        _, cols, client = env()
        async with client:
            response = await client.post("/api/v1/verbs/practice",
                                         json={**load("miniapp/practice-request.json"), **change},
                                         headers=auth_header(USER))

        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"
        assert cols["verb_practice"].docs == []

    async def test_unknown_verb_is_404(self, env):
        _, _, client = env()
        async with client:
            response = await client.post("/api/v1/verbs/practice",
                                         json={**load("miniapp/practice-request.json"), "infinitive": "qwerty"},
                                         headers=auth_header(USER))

        assert response.status_code == 404


class TestWithoutConjugation:

    @pytest.mark.parametrize("path", ["/home", "/suggest?q=and", "/lookup?q=vado",
                                      "/andare/drill/indicativo-presente"])
    async def test_every_route_is_404(self, env, path):
        _, _, client = env(language=replace(TEST_LANGUAGE, conjugation=False))
        async with client:
            response = await _get(client, path)

        assert response.status_code == 404

    async def test_sign_in_is_required(self, env):
        _, _, client = env()
        async with client:
            response = await client.get("/api/v1/verbs/home")

        assert response.status_code == 401
