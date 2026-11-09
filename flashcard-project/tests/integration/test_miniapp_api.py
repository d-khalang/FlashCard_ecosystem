"""
The Mini App API end to end over httpx's ASGI transport, on the real composition root and a real
MongoDB (random database), with the LLM replaced by a fake.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from httpx import ASGITransport

from flashcard.app import study as study_module
from flashcard.miniapp.api import create_app
from flashcard.miniapp.rate_limit import RateLimiter
from flashcard.settings import get_setting
from .study_helpers import add_user, add_word, auth_header

USER = 42
OTHER = 43
BASE = "/api/v1"

CARD_KEYS = {"delivery_id", "expression_id", "value", "direction", "from_storage", "older_settings",
             "definition", "translations", "example", "note"}


@pytest.fixture
async def api(study_core, mongo_cols):
    app = create_app(get_setting())
    app.state.core = study_core
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app
        yield client
    await app.state.prepared.close()


@pytest.fixture
async def ready_user(mongo_cols):
    await add_user(mongo_cols, USER)
    return await add_word(mongo_cols, USER, "andare")


def _as(user_id=USER) -> dict:
    return auth_header(user_id)


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


class TestAudio:

    @pytest.fixture
    def speech(self, study_core):
        synthesize = AsyncMock(return_value=b"mp3-bytes")
        study_core.audio_use_cases.speech = SimpleNamespace(synthesize=synthesize)
        return synthesize

    async def test_a_word_is_generated_once_and_kept(self, api, mongo_cols, ready_user, speech):
        first = await api.get(f"{BASE}/audio/{ready_user}/word", headers=_as())
        second = await api.get(f"{BASE}/audio/{ready_user}/word", headers=_as())

        assert first.status_code == second.status_code == 200
        assert first.content == second.content == b"mp3-bytes"
        assert first.headers["content-type"] == "audio/mpeg" and first.headers["cache-control"] == "no-store"
        speech.assert_awaited_once()
        assert await mongo_cols["audio_words"].count_documents({}) == 1
        user = await mongo_cols["users"].find_one({"user_id": str(USER)})
        assert user["consumption"]["audio_generated"] == 1

    async def test_the_daily_limit_has_its_own_error(self, api, mongo_cols, ready_user, speech):
        await api.get(f"{BASE}/me", headers=_as())
        await mongo_cols["users"].update_one({"user_id": str(USER)}, {"$set": {
            "tier": "normal", "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
            "consumption.consumption_date": datetime.now(timezone.utc).date().isoformat(),
            "consumption.audio_generated": 10_000,
        }})

        response = await api.get(f"{BASE}/audio/{ready_user}/word", headers=_as())

        assert _error(response) == (429, "audio_limit")
        speech.assert_not_awaited()

    async def test_someone_elses_card_is_not_found(self, api, mongo_cols, ready_user, speech):
        await add_user(mongo_cols, OTHER)

        response = await api.get(f"{BASE}/audio/{ready_user}/word", headers=_as(OTHER))

        assert _error(response) == (404, "not_found")
        speech.assert_not_awaited()

    async def test_a_part_that_does_not_exist_is_refused(self, api, ready_user, speech):
        assert _error(await api.get(f"{BASE}/audio/{ready_user}/secret", headers=_as()))[0] == 422

    async def test_a_failing_service_is_a_503(self, api, ready_user, speech):
        speech.side_effect = RuntimeError("403")

        assert _error(await api.get(f"{BASE}/audio/{ready_user}/word", headers=_as())) == (503, "generation_failed")

    async def test_needs_sign_in(self, api, ready_user):
        assert (await api.get(f"{BASE}/audio/{ready_user}/word")).status_code == 401


class TestMe:

    async def test_first_request_creates_the_user_through_record_seen(self, api, mongo_cols):
        response = await api.get(f"{BASE}/me", headers=auth_header(USER, username="noor"))

        assert response.status_code == 200
        user = await mongo_cols["users"].find_one({"user_id": str(USER)})
        assert user["username"] == "noor" and user["created_at"] and user["last_seen_at"]

    async def test_shape_and_values(self, api, mongo_cols, ready_user):
        await add_word(mongo_cols, USER, "resting", last_activity_at=datetime.now(timezone.utc))

        body = (await api.get(f"{BASE}/me", headers=_as())).json()

        assert set(body) == {"reminders_available", "language", "settings", "quota", "words", "options"}
        assert body["language"] == {"code": "it", "name": "Italian", "country": "it"}
        assert set(body["settings"]) == {"target_level", "primary_language", "secondary_language", "review_mode",
                                         "review_interval_minutes", "is_active"}
        assert body["words"] == {"total": 2, "ready": 1, "pending": False}
        assert body["quota"] == {"used": 0, "limit": 20, "card_cost": 2, "section_cost": 1}
        assert body["options"]["levels"] == ["A1", "A2", "B1", "B2", "C1", "C2"]
        assert {"code": "fa", "name": "Persian", "country": "ir"} in body["options"]["languages"]
        assert (body["options"]["min_interval"], body["options"]["max_interval"]) == (15, 240)

    async def test_admins_and_own_key_users_have_no_limit(self, api, mongo_cols):
        await add_user(mongo_cols, USER, tier="admin")

        assert (await api.get(f"{BASE}/me", headers=_as())).json()["quota"]["limit"] is None


class TestStudyFlow:

    async def test_next_grade_undo_roundtrip(self, api, ready_user):
        assert (await api.get(f"{BASE}/study/current", headers=_as())).json() == {"card": None, "undo_available": False}

        next_ = await api.post(f"{BASE}/study/next", headers=_as())
        body = next_.json()
        card = body["card"]
        assert next_.status_code == 200 and body["status"] == "ready"
        assert set(card) == CARD_KEYS
        assert card["delivery_id"] < 0 and card["expression_id"] == ready_user and card["direction"] == "forward"
        assert card["translations"][0] == {"label": "🇬🇧 EN", "country": "gb", "text": "to go"}
        assert card["translations"][1]["country"] == "ir"

        again = (await api.post(f"{BASE}/study/next", headers=_as())).json()
        assert again["card"] == card
        current = (await api.get(f"{BASE}/study/current", headers=_as())).json()
        assert current == {"card": card, "undo_available": False}

        grade = {"delivery_id": card["delivery_id"], "expression_id": card["expression_id"],
                 "direction": "forward", "grade": 4}
        assert (await api.post(f"{BASE}/study/grade", headers=_as(), json=grade)).json() == {
            "status": "graded", "undo_available": True}
        assert (await api.post(f"{BASE}/study/grade", headers=_as(), json=grade)).json() == {"status": "not_pending"}
        assert (await api.get(f"{BASE}/study/current", headers=_as())).json() == {"card": None, "undo_available": True}

        undone = (await api.post(f"{BASE}/study/undo", headers=_as())).json()
        assert undone == {"status": "undone", "card": card}
        assert (await api.post(f"{BASE}/study/undo", headers=_as())).json() == {"status": "nothing_to_undo"}

    async def test_no_words_is_none(self, api, mongo_cols):
        await add_user(mongo_cols, USER)

        assert (await api.post(f"{BASE}/study/next", headers=_as())).json() == {"status": "none"}

    async def test_over_quota_is_the_quota_result(self, api, mongo_cols, ready_user):
        await mongo_cols["users"].update_one({"user_id": str(USER)}, {"$set": {"consumption": {
            "consumption_date": datetime.now(timezone.utc).date().isoformat(),
            "system_api": {"cards_generated": 10, "credits_used": 20}}}})

        body = (await api.post(f"{BASE}/study/next", headers=_as())).json()

        assert body == {"status": "quota", "tier": "normal", "limit": 20}

    async def test_generation_failure_is_503_generation_failed(self, api, ready_user, study_llm):
        study_llm.fail_cards = True

        assert _error(await api.post(f"{BASE}/study/next", headers=_as())) == (503, "generation_failed")

    async def test_the_server_side_timeout_is_generation_failed(self, api, ready_user, study_llm, monkeypatch):
        monkeypatch.setattr(study_module, "GENERATION_TIMEOUT_SECONDS", 0.05)
        study_llm.card_delay = 1.0

        assert _error(await api.post(f"{BASE}/study/next", headers=_as())) == (503, "generation_failed")

    async def test_double_tap_over_http_delivers_one_card(self, api, mongo_cols, ready_user, study_llm):
        await add_word(mongo_cols, USER, "venire")
        study_llm.card_delay = 0.05

        first, second = await asyncio.gather(api.post(f"{BASE}/study/next", headers=_as()),
                                             api.post(f"{BASE}/study/next", headers=_as()))

        assert first.json() == second.json()
        assert study_llm.card_calls == 1

    async def test_prepare_then_next_uses_the_prepared_card(self, api, ready_user, study_llm):
        first = await api.post(f"{BASE}/study/prepare", headers=_as())
        second = await api.post(f"{BASE}/study/prepare", headers=_as())

        assert (first.status_code, first.json()) == (202, {})
        assert second.status_code == 202
        body = (await api.post(f"{BASE}/study/next", headers=_as())).json()

        assert body["status"] == "ready"
        assert study_llm.card_calls == 1

    async def test_failed_prepare_does_not_retry_the_llm_for_a_while(self, api, ready_user, study_llm):
        study_llm.fail_cards = True

        await api.post(f"{BASE}/study/prepare", headers=_as())
        await asyncio.sleep(0.05)
        await api.post(f"{BASE}/study/prepare", headers=_as())
        await asyncio.sleep(0.05)

        assert study_llm.card_calls == 1

    async def test_refresh_replaces_one_section(self, api, ready_user):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]

        body = (await api.post(f"{BASE}/study/refresh", headers=_as(),
                               json={"delivery_id": card["delivery_id"], "section": "definition"})).json()

        assert body["status"] == "ready" and body["card"]["definition"] == "spostarsi da un posto a un altro"
        assert body["card"]["example"] == card["example"]

    async def test_refresh_after_grade_is_not_pending(self, api, ready_user):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        await api.post(f"{BASE}/study/grade", headers=_as(), json={
            "delivery_id": card["delivery_id"], "expression_id": ready_user, "direction": "forward", "grade": 3})

        body = (await api.post(f"{BASE}/study/refresh", headers=_as(),
                               json={"delivery_id": card["delivery_id"], "section": "example"})).json()

        assert body == {"status": "not_pending"}

    async def test_refresh_failure_is_503(self, api, ready_user, study_llm):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        study_llm.fail_sections = True

        response = await api.post(f"{BASE}/study/refresh", headers=_as(),
                                  json={"delivery_id": card["delivery_id"], "section": "example"})

        assert _error(response) == (503, "generation_failed")


class TestOwnership:

    async def test_another_users_expression_id_is_404_and_changes_nothing(self, api, mongo_cols, ready_user):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        await add_user(mongo_cols, OTHER)

        response = await api.post(f"{BASE}/study/grade", headers=_as(OTHER), json={
            "delivery_id": card["delivery_id"], "expression_id": ready_user, "direction": "forward", "grade": 5})

        assert _error(response) == (404, "not_found")
        stored = await mongo_cols["expression"].find_one({"_id": ObjectId(ready_user)})
        assert stored["pending_message_id"] == card["delivery_id"] and "grade_undo" not in stored

    async def test_collection_items_of_others_are_404(self, api, mongo_cols, ready_user):
        await add_user(mongo_cols, OTHER)

        assert _error(await api.get(f"{BASE}/collection/{ready_user}", headers=_as(OTHER))) == (404, "not_found")
        assert _error(await api.delete(f"{BASE}/collection/{ready_user}", headers=_as(OTHER))) == (404, "not_found")
        assert await mongo_cols["expression"].find_one({"_id": ObjectId(ready_user)}) is not None

    @pytest.mark.parametrize("bad_id", ["zzz", "123", "65f000000000000000000zzz", "..%2F..", "null"])
    async def test_malformed_ids_are_404_not_500(self, api, ready_user, bad_id):
        get = await api.get(f"{BASE}/collection/{bad_id}", headers=_as())
        delete = await api.delete(f"{BASE}/collection/{bad_id}", headers=_as())
        grade = await api.post(f"{BASE}/study/grade", headers=_as(), json={
            "delivery_id": -1, "expression_id": bad_id, "direction": "forward", "grade": 3})

        assert [_error(r) for r in (get, delete, grade)] == [(404, "not_found")] * 3

    async def test_responses_never_carry_stored_document_fields(self, api, ready_user):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        texts = [
            (await api.get(f"{BASE}/me", headers=_as())).text,
            (await api.get(f"{BASE}/study/current", headers=_as())).text,
            (await api.get(f"{BASE}/collection", headers=_as())).text,
            (await api.get(f"{BASE}/collection/{ready_user}", headers=_as())).text,
        ]

        for text in texts:
            for field in ("user_id", "_id", "pending_message_id", "last_card", "grade_undo", "current_review",
                          "has_pending", "last_app_grade", "api_config", "consumption", "username"):
                assert f'"{field}"' not in text, field
        assert card["delivery_id"] < 0


class TestCollection:

    async def test_paging_search_detail_and_delete(self, api, mongo_cols):
        await add_user(mongo_cols, USER)
        for value in ("a1", "b2", "c3"):
            await add_word(mongo_cols, USER, value, reps=1)

        first = (await api.get(f"{BASE}/collection?limit=2", headers=_as())).json()
        second = (await api.get(f"{BASE}/collection?limit=2&cursor={first['next_cursor']}", headers=_as())).json()

        assert [i["value"] for i in first["items"]] == ["c3", "b2"] and first["next_cursor"]
        assert [i["value"] for i in second["items"]] == ["a1"] and second["next_cursor"] is None
        assert set(first["items"][0]) == {"id", "value", "reps", "lapses", "created_at"}
        assert first["items"][0]["reps"] == 1 and first["items"][0]["lapses"] == 0

        found = (await api.get(f"{BASE}/collection?q=B2", headers=_as())).json()
        assert [i["value"] for i in found["items"]] == ["b2"] and found["next_cursor"] is None

        item_id = first["items"][0]["id"]
        detail = (await api.get(f"{BASE}/collection/{item_id}", headers=_as())).json()
        assert set(detail) == {"id", "value", "reps", "lapses", "created_at", "content", "generated_at"}
        assert detail["content"] is None and detail["generated_at"] is None

        assert (await api.delete(f"{BASE}/collection/{item_id}", headers=_as())).status_code == 204
        assert _error(await api.delete(f"{BASE}/collection/{item_id}", headers=_as())) == (404, "not_found")
        assert _error(await api.get(f"{BASE}/collection/{item_id}", headers=_as())) == (404, "not_found")

    async def test_detail_has_the_content_of_the_latest_card(self, api, ready_user):
        await api.post(f"{BASE}/study/next", headers=_as())

        detail = (await api.get(f"{BASE}/collection/{ready_user}", headers=_as())).json()

        assert detail["content"]["definition"] and detail["content"]["translations"][0]["country"] == "gb"
        assert detail["generated_at"]

    @pytest.mark.parametrize("query", ["?q=a", "?q=", "?limit=51", "?limit=0", "?cursor=not-an-id",
                                       "?q=" + "x" * 201])
    async def test_bad_queries_are_422(self, api, ready_user, query):
        assert _error(await api.get(f"{BASE}/collection{query}", headers=_as())) == (422, "invalid_request")

    async def test_save_is_201_and_idempotent(self, api, mongo_cols):
        await add_user(mongo_cols, USER)

        first = await api.post(f"{BASE}/collection", headers=_as(), json={"value": "  ciao   mondo "})
        second = await api.post(f"{BASE}/collection", headers=_as(), json={"value": "Ciao mondo"})

        assert (first.status_code, first.json()) == (201, {"status": "saved"})
        assert (second.status_code, second.json()) == (201, {"status": "already_saved"})
        assert (await mongo_cols["expression"].find_one({"user_id": str(USER)}))["value"] == "ciao mondo"

    @pytest.mark.parametrize("body", [{"value": ""}, {"value": "   "}, {"value": "x" * 201}, {}, {"value": 5},
                                      {"value": "ok", "extra": 1}])
    async def test_save_validates_the_body(self, api, mongo_cols, body):
        await add_user(mongo_cols, USER)

        assert _error(await api.post(f"{BASE}/collection", headers=_as(), json=body)) == (422, "invalid_request")

    async def test_import(self, api, mongo_cols):
        await add_user(mongo_cols, USER)

        done = await api.post(f"{BASE}/collection/import", headers=_as(), json={"text": "uno, due"})
        again = await api.post(f"{BASE}/collection/import", headers=_as(), json={"text": "uno"})
        too_long = await api.post(f"{BASE}/collection/import", headers=_as(), json={"text": "x" * 1001})

        assert done.json() == {"status": "imported", "items": ["uno", "due"]}
        assert again.json() == {"status": "all_duplicates"}
        assert too_long.json() == {"status": "too_long", "limit": 1000}


class TestPreview:

    async def test_ready(self, api, mongo_cols):
        await add_user(mongo_cols, USER)

        response = await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})

        body = response.json()
        assert body["status"] == "ready" and body["norm"] == "andare"
        assert set(body["content"]) == {"definition", "translations", "example", "note"}

    async def test_failures_and_limits(self, api, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)

        assert _error(await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "x" * 201})) == (
            422, "invalid_request")
        study_llm.fail_cards = True
        assert _error(await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})) == (
            503, "generation_failed")


class TestSettings:

    async def test_patch_returns_the_settings(self, api, mongo_cols):
        await add_user(mongo_cols, USER)

        response = await api.patch(f"{BASE}/settings", headers=_as(), json={
            "target_level": "B1", "primary_language": "Farsi", "secondary_language": "de",
            "review_mode": "dual", "review_interval_minutes": 60, "is_active": False})

        assert response.json() == {"target_level": "B1", "primary_language": "fa", "secondary_language": "de",
                                   "review_mode": "dual", "review_interval_minutes": 60, "is_active": False}
        off = await api.patch(f"{BASE}/settings", headers=_as(), json={"secondary_language": None})
        assert off.json()["secondary_language"] is None
        assert (await api.patch(f"{BASE}/settings", headers=_as(), json={})).json()["target_level"] == "B1"

    @pytest.mark.parametrize("body", [
        {"target_level": "Z9"}, {"review_interval_minutes": 5}, {"review_interval_minutes": 500},
        {"primary_language": "klingon"}, {"review_mode": "turbo"}, {"target_level": None}, {"tier": "admin"},
    ])
    async def test_bad_values_are_422(self, api, mongo_cols, body):
        await add_user(mongo_cols, USER)

        assert _error(await api.patch(f"{BASE}/settings", headers=_as(), json=body)) == (422, "invalid_request")

    async def test_one_bad_value_changes_nothing(self, api, mongo_cols):
        await add_user(mongo_cols, USER)

        response = await api.patch(f"{BASE}/settings", headers=_as(), json={
            "target_level": "C2", "review_interval_minutes": 1})

        assert response.status_code == 422
        stored = await mongo_cols["users"].find_one({"user_id": str(USER)})
        assert stored.get("target_level") is None


class TestRateLimitsOnTheRealRoutes:

    async def test_llm_routes_are_limited_to_20_a_minute_and_others_to_120(self, api, ready_user):
        assert api.app.state.limiters["llm"].limit == 20 and api.app.state.limiters["general"].limit == 120
        api.app.state.limiters["llm"] = RateLimiter(2)

        statuses = [(await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})).status_code
                    for _ in range(3)]
        general = await api.get(f"{BASE}/study/current", headers=_as())

        assert statuses == [200, 200, 429]
        assert general.status_code == 200
