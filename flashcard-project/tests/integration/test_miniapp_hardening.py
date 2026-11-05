"""
Mini App review fixes against a real MongoDB: users who never opened the bot chat, the LLM allowance,
the failure hold, unintelligible words, the size limits and what undo may overwrite.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from bson import ObjectId
from httpx import ASGITransport

from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardGenerationFailed, GenerationHeld, NoCandidate, ReviewReady
from flashcard.app.study import Delivered, GenerationFailed, Undone
from flashcard.miniapp.api import create_app
from flashcard.miniapp.rate_limit import DailyBudget, RateLimiter
from flashcard.scheduler.scheduler import find_users_due_for_review
from flashcard.services.language_validation import LatinScriptLanguageValidityChecker
from flashcard.settings import get_setting
from .study_helpers import add_user, add_word, auth_header, make_card

USER = 42
OTHER = 43
BASE = "/api/v1"


@pytest.fixture
async def api(study_core, mongo_cols):
    app = create_app(get_setting().model_copy(update={}))
    app.state.core = study_core
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app
        yield client
    await app.state.prepared.close()


def _as(user_id=USER, **kwargs) -> dict:
    return auth_header(user_id, **kwargs)


async def _user(cols, user_id=USER) -> dict:
    return await cols["users"].find_one({"user_id": str(user_id)})


async def _expr(cols, expression_id) -> dict:
    return await cols["expression"].find_one({"_id": ObjectId(expression_id)})


def _stored_card() -> dict:
    return {
        "card": make_card().model_dump(),
        "settings": {"level": "A2", "primary_language": "en", "secondary_language": None},
        "generated_at": datetime.now(timezone.utc) - timedelta(days=2),
    }


class TestUsersWhoNeverOpenedTheChat:

    async def test_a_new_mini_app_user_is_stored_with_a_closed_chat(self, api, mongo_cols):
        await api.get(f"{BASE}/me", headers=_as())

        assert (await _user(mongo_cols))["bot_chat_open"] is False

    async def test_telegram_saying_the_user_allows_writes_opens_it(self, api, mongo_cols):
        await api.get(f"{BASE}/me", headers=_as(allows_write_to_pm=True))
        await api.get(f"{BASE}/me", headers=_as(OTHER, allows_write_to_pm=False))

        assert (await _user(mongo_cols))["bot_chat_open"] is True
        assert (await _user(mongo_cols, OTHER))["bot_chat_open"] is False

    async def test_the_app_never_closes_a_chat_the_bot_opened(self, api, mongo_cols):
        await add_user(mongo_cols, USER, bot_chat_open=True)

        await api.get(f"{BASE}/me", headers=_as())

        assert (await _user(mongo_cols))["bot_chat_open"] is True

    async def test_any_bot_interaction_opens_the_chat(self, study_core, mongo_cols):
        await study_core.user_service.record_seen(USER, "x", bot_chat_open=False)
        assert (await _user(mongo_cols))["bot_chat_open"] is False

        await study_core.user_service.record_seen(USER, "x")  # what the bot's middleware calls

        assert (await _user(mongo_cols))["bot_chat_open"] is True

    async def test_me_says_whether_reminders_can_be_sent(self, api, mongo_cols):
        closed = (await api.get(f"{BASE}/me", headers=_as())).json()
        await add_user(mongo_cols, OTHER)  # an existing bot user: no flag stored
        existing = (await api.get(f"{BASE}/me", headers=_as(OTHER))).json()

        assert closed["reminders_available"] is False and existing["reminders_available"] is True

    async def test_the_scheduler_does_not_pick_them_up(self, study_core, mongo_cols):
        await add_user(mongo_cols, 1, bot_chat_open=False, has_pending=False)
        await add_user(mongo_cols, 2, has_pending=False)  # an existing user: no flag
        await add_user(mongo_cols, 3, bot_chat_open=True, has_pending=False)
        for user_id in (1, 2, 3):
            await add_word(mongo_cols, user_id, "andare")

        due = await find_users_due_for_review(study_core.user_service, "current_review")
        due_legacy = await find_users_due_for_review(study_core.user_service)

        assert sorted(u.user_id for u in due) == [2, 3]
        assert sorted(u.user_id for u in due_legacy) == [2, 3]


@pytest.fixture
async def ready_user(mongo_cols):
    await add_user(mongo_cols, USER, bot_chat_open=True)
    return await add_word(mongo_cols, USER, "andare")


class TestLlmAllowance:

    async def test_the_daily_budget_stops_calls_that_cost_no_quota(self, api, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        api.app.state.budget = DailyBudget(2)
        study_llm.unclear = {"blah"}

        codes = [(await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "blah"})) for _ in range(3)]

        assert [r.status_code for r in codes] == [200, 200, 429]
        assert [r.json().get("status") for r in codes[:2]] == ["unclear", "unclear"]
        assert 1 <= int(codes[2].headers["Retry-After"]) <= 86400
        assert codes[2].json()["error"]["code"] == "rate_limited"
        assert study_llm.card_calls == 2

    async def test_every_llm_route_is_charged(self, api, mongo_cols, ready_user, study_llm):
        api.app.state.budget = DailyBudget(1)
        await api.post(f"{BASE}/collection/import", headers=_as(), json={"text": "uno"})

        import_ = await api.post(f"{BASE}/collection/import", headers=_as(), json={"text": "due"})
        preview = await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})
        next_ = await api.post(f"{BASE}/study/next", headers=_as())

        assert [r.status_code for r in (import_, preview, next_)] == [429] * 3

    async def test_a_refused_prepare_makes_no_llm_call_and_leaves_nothing_prepared(self, api, ready_user, study_llm):
        api.app.state.budget = DailyBudget(0)

        response = await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task

        assert response.status_code == 202
        assert study_llm.card_calls == 0
        assert await api.app.state.prepared.take(USER) is None

    async def test_a_prepare_that_finds_no_card_costs_nothing(self, api, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        api.app.state.budget = DailyBudget(1)

        await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task

        assert api.app.state.budget.charge(USER) == 0

    async def test_a_prepare_over_quota_with_a_stored_card_costs_nothing(
            self, api, mongo_cols, study_core, study_llm, monkeypatch):
        monkeypatch.setattr(study_core.quota, "check", lambda user, kind: QuotaExceeded(tier="normal", limit=10))
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "andare", last_card=_stored_card())
        api.app.state.budget = DailyBudget(1)

        await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task

        assert study_llm.card_calls == 0
        assert api.app.state.budget.charge(USER) == 0

    async def test_admins_are_exempt(self, api, mongo_cols, study_llm):
        await add_user(mongo_cols, USER, tier="admin")
        api.app.state.budget = DailyBudget(1)

        statuses = [(await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})).status_code
                    for _ in range(3)]

        assert statuses == [200, 200, 200]

    async def test_budgets_are_per_user(self, api, mongo_cols):
        await add_user(mongo_cols, USER)
        await add_user(mongo_cols, OTHER)
        api.app.state.budget = DailyBudget(1)

        first = await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})
        other = await api.post(f"{BASE}/cards/preview", headers=_as(OTHER), json={"text": "andare"})

        assert (first.status_code, other.status_code) == (200, 200)

    async def test_resuming_costs_neither_the_budget_nor_the_minute_limit(self, api, ready_user):
        api.app.state.limiters["llm"] = RateLimiter(1)
        api.app.state.budget = DailyBudget(1)

        statuses = [(await api.post(f"{BASE}/study/next", headers=_as())).status_code for _ in range(5)]

        assert statuses == [200] * 5
        assert api.app.state.budget.charge(USER) > 0  # the one real generation used it up

    async def test_using_the_prepared_card_and_repeated_prepares_cost_nothing_extra(self, api, ready_user, study_llm):
        api.app.state.limiters["llm"] = RateLimiter(1)
        api.app.state.budget = DailyBudget(1)

        prepares = [(await api.post(f"{BASE}/study/prepare", headers=_as())).status_code for _ in range(3)]
        next_ = await api.post(f"{BASE}/study/next", headers=_as())

        assert prepares == [202] * 3 and next_.status_code == 200
        assert study_llm.card_calls == 1

    async def test_a_prepare_that_cannot_start_costs_nothing(self, api, ready_user, study_llm):
        study_llm.fail_cards = True
        await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task  # wait for the failure
        api.app.state.budget = DailyBudget(1)

        await api.post(f"{BASE}/study/prepare", headers=_as())  # held: starts nothing

        assert api.app.state.budget.charge(USER) == 0

    async def test_the_minute_limit_still_applies_to_real_calls(self, api, mongo_cols):
        await add_user(mongo_cols, USER)
        api.app.state.limiters["llm"] = RateLimiter(2)

        statuses = [(await api.post(f"{BASE}/cards/preview", headers=_as(), json={"text": "andare"})).status_code
                    for _ in range(3)]

        assert statuses == [200, 200, 429]

    async def test_refresh_is_charged_when_it_calls_the_llm(self, api, ready_user, study_llm):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        api.app.state.budget = DailyBudget(1)
        body = {"delivery_id": card["delivery_id"], "section": "example"}

        first = await api.post(f"{BASE}/study/refresh", headers=_as(), json=body)
        second = await api.post(f"{BASE}/study/refresh", headers=_as(), json=body)

        assert (first.status_code, second.status_code) == (200, 429)
        wrong = await api.post(f"{BASE}/study/refresh", headers=_as(), json={**body, "delivery_id": -1})
        assert wrong.json() == {"status": "not_pending"}  # no LLM call, so no charge either way


class TestFailureHold:

    async def test_next_after_a_failure_is_refused_without_calling_the_llm(self, api, ready_user, study_llm):
        study_llm.fail_cards = True

        first = await api.post(f"{BASE}/study/next", headers=_as())
        calls = study_llm.card_calls
        second = await api.post(f"{BASE}/study/next", headers=_as())

        assert (first.status_code, second.status_code) == (503, 503)
        assert second.json()["error"]["code"] == "generation_failed"
        assert calls == 1 and study_llm.card_calls == 1

    async def test_a_failed_prepare_holds_next_too(self, api, ready_user, study_llm):
        study_llm.fail_cards = True
        await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task

        response = await api.post(f"{BASE}/study/next", headers=_as())

        assert response.status_code == 503 and study_llm.card_calls == 1

    async def test_the_hold_ends(self, api, ready_user, study_llm):
        study_llm.fail_cards = True
        await api.post(f"{BASE}/study/next", headers=_as())
        study_llm.fail_cards = False
        api.app.state.prepared._slots[USER].failed_until = 0  # time passed

        assert (await api.post(f"{BASE}/study/next", headers=_as())).status_code == 200

    async def test_an_unclear_word_in_prepare_does_not_hold_next(self, api, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "xyzzy", age_days=30)
        good = await add_word(mongo_cols, USER, "andare", age_days=1)
        study_llm.unclear = {"xyzzy"}
        await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task

        response = await api.post(f"{BASE}/study/next", headers=_as())

        assert response.status_code == 200 and response.json()["card"]["expression_id"] == good

    async def test_a_refused_generation_still_sends_a_stored_card(self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        expression_id = await add_word(mongo_cols, USER, "andare", last_card=_stored_card())

        result = await study_core.review_use_cases.prepare_next(USER, before_generation=GenerationHeld)

        assert isinstance(result, ReviewReady) and result.from_storage
        assert result.expression_id == expression_id and study_llm.card_calls == 0

    async def test_a_refused_generation_without_a_stored_card_is_the_result(self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "andare")

        result = await study_core.review_use_cases.prepare_next(USER, before_generation=GenerationHeld)

        assert isinstance(result, GenerationHeld) and study_llm.card_calls == 0

    async def test_a_waiting_card_is_still_returned_during_the_hold(self, api, ready_user):
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        api.app.state.prepared.hold(USER)

        again = await api.post(f"{BASE}/study/next", headers=_as())

        assert again.status_code == 200 and again.json()["card"] == card

    async def test_nothing_to_study_is_not_a_failure(self, api, mongo_cols):
        await add_user(mongo_cols, USER)
        await api.post(f"{BASE}/study/prepare", headers=_as())
        await api.app.state.prepared._slots[USER].task

        assert (await api.post(f"{BASE}/study/next", headers=_as())).json() == {"status": "none"}


class TestOverQuota:

    @pytest.fixture
    def over_quota(self, study_core, monkeypatch):
        monkeypatch.setattr(study_core.quota, "check", lambda user, kind: QuotaExceeded(tier="normal", limit=10))

    async def test_the_app_uses_a_stored_word_when_the_top_word_has_none(
            self, api, mongo_cols, study_llm, over_quota):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "nuova", age_days=30)
        stored = await add_word(mongo_cols, USER, "andare", age_days=1, reps=5, ewma_grade=4.5, last_card=_stored_card())

        response = await api.post(f"{BASE}/study/next", headers=_as())

        card = response.json()["card"]
        assert card["expression_id"] == stored and card["from_storage"] is True
        assert study_llm.card_calls == 0

    async def test_the_app_answers_quota_when_no_word_has_a_stored_card(self, api, mongo_cols, over_quota):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "nuova")

        response = await api.post(f"{BASE}/study/next", headers=_as())

        assert response.json()["status"] == "quota"

    async def test_the_bot_path_keeps_the_top_word_rule(self, study_core, mongo_cols, over_quota):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "nuova", age_days=30)
        await add_word(mongo_cols, USER, "andare", age_days=1, reps=5, ewma_grade=4.5, last_card=_stored_card())

        assert isinstance(await study_core.review_use_cases.prepare_next(USER), QuotaExceeded)


class TestUnintelligibleWord:

    async def test_the_word_is_deferred_and_the_next_one_is_tried(self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        bad = await add_word(mongo_cols, USER, "xyzzy", age_days=10)  # oldest: picked first (priority has a random part of up to 0.08, so ages are far apart)
        good = await add_word(mongo_cols, USER, "andare", age_days=2)
        study_llm.unclear = {"xyzzy"}

        result = await study_core.study_use_cases.next(USER)

        assert isinstance(result, Delivered) and result.card.expression_id == good
        deferred = await _expr(mongo_cols, bad)
        assert deferred["last_activity_at"] is not None and deferred.get("pending_message_id") is None
        assert "last_card" not in deferred
        assert study_llm.card_calls == 2

    async def test_after_one_retry_it_gives_up(self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        for value in ("aaa", "bbb", "ccc"):
            await add_word(mongo_cols, USER, value)
        study_llm.unclear = {"aaa", "bbb", "ccc"}

        result = await study_core.study_use_cases.next(USER)

        assert result == GenerationFailed(unclear=True)
        assert study_llm.card_calls == 2  # not a loop over every word
        deferred = [d async for d in mongo_cols["expression"].find({"last_activity_at": {"$ne": None}})]
        assert len(deferred) == 2

    async def test_the_api_answers_503_then_study_goes_on_with_other_words(self, api, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        for value, age in (("aaa", 30), ("bbb", 3), ("ccc", 1)):
            await add_word(mongo_cols, USER, value, age_days=age)
        study_llm.unclear = {"aaa", "bbb"}

        failed = await api.post(f"{BASE}/study/next", headers=_as())
        api.app.state.prepared._slots[USER].failed_until = 0
        again = await api.post(f"{BASE}/study/next", headers=_as())

        assert failed.status_code == 503
        assert again.status_code == 200 and again.json()["card"]["value"] == "ccc"

    async def test_a_provider_error_defers_nothing(self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        expression_id = await add_word(mongo_cols, USER, "andare")
        study_llm.fail_cards = True

        assert await study_core.study_use_cases.next(USER) == GenerationFailed()

        assert (await _expr(mongo_cols, expression_id)).get("last_activity_at") is None

    async def test_the_bot_path_defers_too_and_still_raises(self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        bad = await add_word(mongo_cols, USER, "xyzzy", age_days=10)
        good = await add_word(mongo_cols, USER, "andare", age_days=2)
        study_llm.unclear = {"xyzzy"}
        review = study_core.review_use_cases

        with pytest.raises(CardGenerationFailed):
            await review.prepare_next(USER)
        second = await review.prepare_next(USER)

        assert isinstance(second, ReviewReady) and second.expression_id == good
        assert (await _expr(mongo_cols, bad))["last_activity_at"] is not None

    async def test_a_word_with_a_stored_card_is_not_deferred_the_stored_card_is_sent(
            self, study_core, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        expression_id = await add_word(mongo_cols, USER, "andare")
        ready = await study_core.review_use_cases.prepare_next(USER)
        await study_core.review_use_cases.mark_sent(USER, ready, 555)
        await study_core.review_use_cases.grade(USER, expression_id, 4, "forward", message_id=555)
        await mongo_cols["expression"].update_one({"_id": ObjectId(expression_id)}, {"$set": {"last_activity_at": None}})
        before = (await _expr(mongo_cols, expression_id))["last_activity_at"]
        study_llm.unclear = {"andare"}

        result = await study_core.review_use_cases.prepare_next(USER)

        assert isinstance(result, ReviewReady) and result.from_storage
        assert (await _expr(mongo_cols, expression_id))["last_activity_at"] == before

    async def test_deferring_is_scoped_to_the_users_own_card_and_touches_one_field(self, study_core, mongo_cols):
        expression_id = await add_word(mongo_cols, USER, "andare", reps=3)
        before = await _expr(mongo_cols, expression_id)

        await study_core.expression_service.defer_review(OTHER, expression_id)
        assert await _expr(mongo_cols, expression_id) == before
        await study_core.expression_service.defer_review(USER, "not-an-id")
        await study_core.expression_service.defer_review(USER, expression_id)

        after = await _expr(mongo_cols, expression_id)
        assert after.pop("last_activity_at") is not None
        before.pop("last_activity_at", None)
        assert after == before


class TestCollectionLimits:

    @pytest.fixture
    def small(self, api):
        api.app.state.settings = api.app.state.settings.model_copy(update={"MINIAPP_MAX_WORDS": 2})
        return api

    async def test_text_the_validator_rejects_is_invalid(self, api, study_core, mongo_cols):
        await add_user(mongo_cols, USER)
        study_core.creation_use_cases.validator = LatinScriptLanguageValidityChecker(None)

        response = await api.post(f"{BASE}/collection", headers=_as(), json={"value": "اسم"})

        assert (response.status_code, response.json()) == (200, {"status": "invalid", "suggestions": []})
        assert await mongo_cols["expression"].count_documents({}) == 0

    async def test_valid_text_is_saved_in_the_validators_normal_form(self, api, study_core, mongo_cols):
        await add_user(mongo_cols, USER)
        study_core.creation_use_cases.validator = LatinScriptLanguageValidityChecker(None)

        response = await api.post(f"{BASE}/collection", headers=_as(), json={"value": "Ciao  Mondo"})

        assert (response.status_code, response.json()) == (201, {"status": "saved"})

    async def test_save_stops_at_the_limit_but_still_reports_duplicates_below_it(self, small, mongo_cols):
        await add_user(mongo_cols, USER)
        saved = [(await small.post(f"{BASE}/collection", headers=_as(), json={"value": v})) for v in ("a1", "b2")]
        full = await small.post(f"{BASE}/collection", headers=_as(), json={"value": "c3"})

        assert [r.status_code for r in saved] == [201, 201]
        assert (full.status_code, full.json()) == (200, {"status": "too_many", "limit": 2})
        assert await mongo_cols["expression"].count_documents({}) == 2

    async def test_import_at_the_limit_is_refused_before_calling_the_llm(self, small, mongo_cols, study_llm):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "a1")
        await add_word(mongo_cols, USER, "b2")
        small.app.state.budget = DailyBudget(1)

        response = await small.post(f"{BASE}/collection/import", headers=_as(), json={"text": "uno, due"})

        assert response.json() == {"status": "too_many", "limit": 2}
        assert small.app.state.budget.charge(USER) == 0  # nothing was charged

    async def test_an_import_that_would_pass_the_limit_saves_nothing(self, small, mongo_cols):
        await add_user(mongo_cols, USER)
        await add_word(mongo_cols, USER, "a1")

        response = await small.post(f"{BASE}/collection/import", headers=_as(), json={"text": "uno, due"})

        assert response.json() == {"status": "too_many", "limit": 2}
        assert await mongo_cols["expression"].count_documents({}) == 1

    async def test_an_import_that_fits_is_saved_as_strings(self, small, mongo_cols):
        await add_user(mongo_cols, USER)

        response = await small.post(f"{BASE}/collection/import", headers=_as(), json={"text": "uno, due"})

        assert response.json() == {"status": "imported", "items": ["uno", "due"]}

    async def test_the_bot_path_has_no_limit(self, study_core, mongo_cols):
        await add_user(mongo_cols, USER)
        for value in ("a1", "b2", "c3"):
            await study_core.creation_use_cases.save(USER, value)

        assert (await study_core.expression_service.count_words(USER)).total == 3


class TestPendingFlag:

    async def test_words_pending_follows_the_waiting_card(self, api, ready_user):
        async def pending():
            return (await api.get(f"{BASE}/me", headers=_as())).json()["words"]["pending"]

        assert await pending() is False
        card = (await api.post(f"{BASE}/study/next", headers=_as())).json()["card"]
        assert await pending() is True
        await api.post(f"{BASE}/study/grade", headers=_as(), json={
            "delivery_id": card["delivery_id"], "expression_id": ready_user, "direction": "forward", "grade": 3})
        assert await pending() is False

    async def test_a_review_whose_card_is_gone_is_not_pending(self, api, mongo_cols, ready_user):
        await api.post(f"{BASE}/study/next", headers=_as())
        await mongo_cols["expression"].update_one({"_id": ObjectId(ready_user)}, {"$unset": {"last_card": ""}})

        assert (await api.get(f"{BASE}/me", headers=_as())).json()["words"]["pending"] is False


class TestUndoDoesNotOverwriteNewerState:

    async def _graded_in_app(self, core, cols):
        await add_user(cols, USER)
        first = await add_word(cols, USER, "andare", age_days=30)
        second = await add_word(cols, USER, "venire", age_days=3)
        card = (await core.study_use_cases.next(USER)).card
        assert card.expression_id == first
        await core.study_use_cases.grade(USER, first, 4, "forward", delivery_id=card.delivery_id)
        return card, second

    async def test_a_newer_bot_grade_keeps_its_review_interval_but_the_stats_are_restored(self, study_core, mongo_cols):
        card, second = await self._graded_in_app(study_core, mongo_cols)
        review = study_core.review_use_cases
        ready = await review.prepare_next(USER)
        assert ready.expression_id == second
        await review.mark_sent(USER, ready, 555)
        await review.grade(USER, second, 3, "forward", message_id=555)
        bot_graded_at = (await _user(mongo_cols))["last_reviewed_at"]

        result = await study_core.study_use_cases.undo(USER)

        assert isinstance(result, Undone)
        user = await _user(mongo_cols)
        assert user["last_reviewed_at"] == bot_graded_at  # not rolled back to "never"
        assert user["current_review"]["message_id"] == card.delivery_id  # nothing newer was waiting
        assert "last_app_grade" not in user
        expression = await _expr(mongo_cols, card.expression_id)
        assert (expression.get("reps") or 0) == 0 and expression["pending_message_id"] == card.delivery_id

    async def test_a_newer_unanswered_bot_card_stays_the_current_review(self, study_core, mongo_cols):
        card, second = await self._graded_in_app(study_core, mongo_cols)
        review = study_core.review_use_cases
        ready = await review.prepare_next(USER)
        await review.mark_sent(USER, ready, 555)

        result = await study_core.study_use_cases.undo(USER)

        assert isinstance(result, Undone)
        user = await _user(mongo_cols)
        assert user["current_review"]["message_id"] == 555 and user["current_review"]["expression_id"] == second
        assert (await _expr(mongo_cols, card.expression_id))["pending_message_id"] == card.delivery_id
        assert "last_app_grade" not in user

    async def test_a_newer_app_card_is_replaced_by_the_restored_one(self, study_core, mongo_cols):
        card, second = await self._graded_in_app(study_core, mongo_cols)
        newer = (await study_core.study_use_cases.next(USER)).card
        assert newer.expression_id == second

        await study_core.study_use_cases.undo(USER)

        assert (await _user(mongo_cols))["current_review"]["message_id"] == card.delivery_id

    async def test_an_untouched_interval_is_restored_to_what_it_was(self, study_core, mongo_cols):
        await add_user(mongo_cols, USER, last_reviewed_at=datetime.now(timezone.utc) - timedelta(hours=5))
        before = (await _user(mongo_cols))["last_reviewed_at"]
        first = await add_word(mongo_cols, USER, "andare")
        card = (await study_core.study_use_cases.next(USER)).card
        await study_core.study_use_cases.grade(USER, first, 4, "forward", delivery_id=card.delivery_id)
        assert (await _user(mongo_cols))["last_reviewed_at"] != before

        await study_core.study_use_cases.undo(USER)

        assert (await _user(mongo_cols))["last_reviewed_at"] == before


class TestSignInOrder:

    async def test_a_client_stuck_on_429_writes_nothing(self, api, mongo_cols):
        api.app.state.limiters["general"] = RateLimiter(1)
        await add_user(mongo_cols, USER)
        await mongo_cols["users"].update_one({"user_id": str(USER)}, {"$set": {"last_seen_at": None}})

        await api.get(f"{BASE}/me", headers=_as())
        seen = (await _user(mongo_cols))["last_seen_at"]
        await mongo_cols["users"].update_one({"user_id": str(USER)}, {"$set": {"last_seen_at": None}})
        refused = await api.get(f"{BASE}/me", headers=_as())

        assert seen is not None and refused.status_code == 429
        assert (await _user(mongo_cols))["last_seen_at"] is None
