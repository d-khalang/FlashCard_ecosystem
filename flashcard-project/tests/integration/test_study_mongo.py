"""
StudyUseCases against a real MongoDB (compare-and-set behavior cannot be shown on a fake):
deliver, resume, grade once, undo and refresh, plus the services' new queries.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from flashcard.app import study as study_module
from flashcard.app.collection import BadCursor, ItemPage, NotFound, QueryTooShort
from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardNotFound, Graded, NoCandidate, NotPending
from flashcard.app.review_schedule import awaiting_answer
from flashcard.app.study import (
    Delivered, GenerationFailed, NothingToUndo, Refreshed, Undone,
)
from flashcard.services.expression import InvalidCursor
from .study_helpers import add_user, add_word

USER = 42
OTHER = 43


async def _user(cols, user_id=USER) -> dict:
    return await cols["users"].find_one({"user_id": str(user_id)})


async def _expr(cols, expression_id) -> dict:
    return await cols["expression"].find_one({"_id": ObjectId(expression_id)})


async def _delivered(study_core, user_id=USER):
    result = await study_core.study_use_cases.next(user_id)
    assert isinstance(result, Delivered), result
    return result.card


@pytest.fixture
async def setup(study_core, mongo_cols):
    """One user with one word that is ready for review."""
    await add_user(mongo_cols, USER)
    expression_id = await add_word(mongo_cols, USER, "andare")
    return study_core, mongo_cols, expression_id


class TestDelivery:

    async def test_delivers_with_a_negative_id_and_records_the_delivery(self, setup):
        core, cols, expression_id = setup

        card = await _delivered(core)

        assert -(2**53 - 1) <= card.delivery_id <= -1
        assert (card.expression_id, card.value, card.direction) == (expression_id, "andare", "forward")
        assert (card.from_storage, card.older_settings) == (False, False)
        expression = await _expr(cols, expression_id)
        assert expression["pending_message_id"] == card.delivery_id
        assert expression["last_card"]["card"]["learning_definition"]
        assert expression["last_activity_at"] is not None
        user = await _user(cols)
        assert user["current_review"]["message_id"] == card.delivery_id
        assert user["consumption"]["system_api"]["cards_generated"] == 1

    async def test_does_not_set_the_legacy_pause_flag_or_pause_reminders(self, setup):
        core, cols, _ = setup

        await _delivered(core)

        user = await _user(cols)
        assert not user.get("has_pending")
        user_db = await core.user_service.get_user(USER)
        assert user_db.current_review.in_app
        assert awaiting_answer(user_db) is False

    async def test_a_second_next_returns_the_waiting_card(self, setup):
        core, _, _ = setup
        first = await _delivered(core)

        second = await _delivered(core)

        assert second == first
        assert core.llm_service.card_calls == 1

    async def test_a_double_tap_generates_and_delivers_once(self, setup):
        core, cols, expression_id = setup
        core.llm_service.card_delay = 0.05
        await add_word(cols, USER, "venire")  # a second candidate that a second delivery would take

        first, second = await asyncio.gather(core.study_use_cases.next(USER), core.study_use_cases.next(USER))

        assert isinstance(first, Delivered) and isinstance(second, Delivered)
        assert first.card.delivery_id == second.card.delivery_id
        assert core.llm_service.card_calls == 1
        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 1
        pending = [d async for d in cols["expression"].find({"pending_message_id": {"$ne": None}})]
        assert len(pending) == 1

    async def test_no_words_means_no_candidate(self, study_core, mongo_cols):
        await add_user(mongo_cols, USER)

        assert await study_core.study_use_cases.next(USER) == NoCandidate()

    async def test_generation_failure_writes_nothing(self, setup):
        core, cols, expression_id = setup
        core.llm_service.fail_cards = True

        assert await core.study_use_cases.next(USER) == GenerationFailed()

        assert (await _expr(cols, expression_id)).get("pending_message_id") is None
        assert "current_review" not in await _user(cols)

    async def test_generation_is_limited_to_the_server_side_timeout(self, setup, monkeypatch):
        core, _, _ = setup
        monkeypatch.setattr(study_module, "GENERATION_TIMEOUT_SECONDS", 0.05)
        core.llm_service.card_delay = 1.0

        assert await core.study_use_cases.next(USER) == GenerationFailed()

    async def test_over_quota_sends_the_stored_card_free(self, setup):
        core, cols, expression_id = setup
        await _delivered(core)  # makes the stored card
        await core.study_use_cases.grade(USER, expression_id, 4, "forward",
                                         delivery_id=(await _expr(cols, expression_id))["pending_message_id"])
        # Back to ready, and today's credits used up (normal tier limit 20; the test users are past their trial).
        await cols["expression"].update_one({"_id": ObjectId(expression_id)}, {"$set": {"last_activity_at": None}})
        await cols["users"].update_one({"user_id": str(USER)}, {"$set": {"consumption": {
            "consumption_date": datetime.now(timezone.utc).date().isoformat(),
            "system_api": {"cards_generated": 10, "credits_used": 20}}}})
        calls = core.llm_service.card_calls

        card = await _delivered(core)

        assert card.from_storage is True
        assert core.llm_service.card_calls == calls
        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 10

    async def test_over_quota_without_a_stored_card_is_a_quota_result(self, setup):
        core, cols, _ = setup
        await cols["users"].update_one({"user_id": str(USER)}, {"$set": {"consumption": {
            "consumption_date": datetime.now(timezone.utc).date().isoformat(),
            "system_api": {"cards_generated": 10, "credits_used": 20}}}})

        assert isinstance(await core.study_use_cases.next(USER), QuotaExceeded)


class TestResume:

    async def test_a_card_the_bot_delivered_is_resumed_with_its_message_id(self, setup):
        core, cols, expression_id = setup
        ready = await core.review_use_cases.prepare_next(USER)
        await core.review_use_cases.mark_sent(USER, ready, 777)
        calls = core.llm_service.card_calls

        state = await core.study_use_cases.current(USER)
        result = await core.study_use_cases.next(USER)

        assert state.card.delivery_id == 777 and state.card.expression_id == expression_id
        assert result == Delivered(state.card)
        assert core.llm_service.card_calls == calls

    async def test_grading_the_resumed_card_resolves_the_old_bot_message(self, setup):
        core, _, expression_id = setup
        ready = await core.review_use_cases.prepare_next(USER)
        await core.review_use_cases.mark_sent(USER, ready, 777)

        graded = await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=777)
        late_tap = await core.review_use_cases.grade(USER, expression_id, 4, "forward", message_id=777)

        assert graded == Graded()
        assert late_tap == NotPending()

    async def test_direction_unknown_is_forward(self, setup):
        core, cols, _ = setup
        await _delivered(core)
        await cols["users"].update_one({"user_id": str(USER)}, {"$set": {"current_review.direction": "unknown"}})

        assert (await core.study_use_cases.current(USER)).card.direction == "forward"

    async def test_from_storage_when_the_stored_card_is_much_older_than_its_delivery(self, setup):
        core, cols, expression_id = setup
        await _delivered(core)
        sent_at = (await _user(cols))["current_review"]["sent_at"]
        await cols["expression"].update_one({"_id": ObjectId(expression_id)},
                                            {"$set": {"last_card.generated_at": sent_at - timedelta(minutes=5)}})

        assert (await core.study_use_cases.current(USER)).card.from_storage is True

    async def test_a_review_without_a_stored_card_is_not_resumed(self, setup):
        core, cols, expression_id = setup
        await _delivered(core)
        await cols["expression"].update_one({"_id": ObjectId(expression_id)}, {"$unset": {"last_card": ""}})

        assert (await core.study_use_cases.current(USER)).card is None

    async def test_a_review_whose_card_was_graded_elsewhere_is_not_resumed(self, setup):
        core, cols, expression_id = setup
        await _delivered(core)
        await cols["expression"].update_one({"_id": ObjectId(expression_id)}, {"$set": {"pending_message_id": None}})

        assert (await core.study_use_cases.current(USER)).card is None


class TestPrepareAhead:

    async def test_a_valid_prepared_card_is_delivered_without_another_generation(self, setup):
        core, _, expression_id = setup
        ready = await core.study_use_cases.prepare(USER)

        async def prepared():
            return ready

        result = await core.study_use_cases.next(USER, take_prepared=prepared)

        assert isinstance(result, Delivered) and result.card.expression_id == expression_id
        assert core.llm_service.card_calls == 1

    async def test_a_card_that_went_on_cooldown_meanwhile_is_not_delivered(self, setup):
        core, cols, expression_id = setup
        ready = await core.study_use_cases.prepare(USER)
        await cols["expression"].update_one({"_id": ObjectId(expression_id)},
                                            {"$set": {"last_activity_at": datetime.now(timezone.utc)}})

        async def prepared():
            return ready

        assert await core.study_use_cases.next(USER, take_prepared=prepared) == NoCandidate()

    async def test_changed_settings_make_the_prepared_card_stale(self, setup):
        core, _, _ = setup
        ready = await core.study_use_cases.prepare(USER)
        await core.settings_use_cases.set_level(USER, "C1")

        async def prepared():
            return ready

        result = await core.study_use_cases.next(USER, take_prepared=prepared)

        assert isinstance(result, Delivered)
        assert core.llm_service.card_calls == 2

    async def test_preparing_counts_nothing(self, setup):
        core, cols, expression_id = setup

        await core.study_use_cases.prepare(USER)

        assert "consumption" not in await _user(cols) or (
            (await _user(cols))["consumption"].get("system_api", {}).get("cards_generated", 0) == 0)
        assert (await _expr(cols, expression_id)).get("pending_message_id") is None


class TestGrade:

    async def test_grades_once_per_delivery(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)

        first = await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        second = await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)

        assert (first, second) == (Graded(), NotPending())
        expression = await _expr(cols, expression_id)
        assert expression["reps"] == 1
        assert expression["pending_message_id"] is None
        assert expression["grade_undo"]["delivery_id"] == card.delivery_id
        user = await _user(cols)
        assert "current_review" not in user
        assert user["last_reviewed_at"] is not None
        assert user["last_app_grade"]["delivery_id"] == card.delivery_id
        assert (await core.study_use_cases.current(USER)).undo_available is True

    async def test_a_stale_delivery_id_is_not_pending(self, setup):
        core, cols, expression_id = setup
        await _delivered(core)

        assert await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=-5) == NotPending()
        assert (await _expr(cols, expression_id)).get("reps", 0) == 0

    async def test_another_users_expression_is_not_found_and_untouched(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await add_user(cols, OTHER)

        result = await core.study_use_cases.grade(OTHER, expression_id, 5, "forward", delivery_id=card.delivery_id)

        assert result == CardNotFound()
        expression = await _expr(cols, expression_id)
        assert expression["pending_message_id"] == card.delivery_id
        assert "grade_undo" not in expression

    @pytest.mark.parametrize("bad_id", ["zzz", "", "65f0", "../../etc"])
    async def test_a_malformed_expression_id_is_not_found(self, setup, bad_id):
        core, _, _ = setup

        assert await core.study_use_cases.grade(USER, bad_id, 4, "forward", delivery_id=-1) == CardNotFound()

    async def test_an_invalid_grade_raises_before_anything_is_written(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)

        with pytest.raises(ValueError):
            await core.study_use_cases.grade(USER, expression_id, 9, "forward", delivery_id=card.delivery_id)

        assert (await _expr(cols, expression_id))["pending_message_id"] == card.delivery_id

    async def test_a_bot_style_grade_drops_the_undo_snapshot(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        await core.expression_service.update_expression_sent(expression_id, 555, user_id=USER)

        await core.review_use_cases.grade(USER, expression_id, 3, "forward", message_id=555)

        assert "grade_undo" not in await _expr(cols, expression_id)


class TestUndo:

    async def test_restores_the_card_and_the_review_state(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        expression_before = await _expr(cols, expression_id)
        user_before = await _user(cols)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)

        result = await core.study_use_cases.undo(USER)

        assert isinstance(result, Undone)
        assert result.card.delivery_id == card.delivery_id and result.card.expression_id == expression_id
        expression = await _expr(cols, expression_id)
        # A word never reviewed has no counters; restored as zeros, which read the same.
        for field in ("reps", "lapses", "success_streak", "ewma_grade", "last_grade"):
            assert (expression.get(field) or 0) == (expression_before.get(field) or 0), field
        for field in ("last_interaction_at", "last_activity_at"):
            assert expression.get(field) == expression_before.get(field), field
        assert expression["pending_message_id"] == card.delivery_id
        assert "grade_undo" not in expression
        user = await _user(cols)
        assert user["current_review"]["message_id"] == card.delivery_id
        assert user["current_review"]["sent_at"] == user_before["current_review"]["sent_at"]
        assert user.get("last_reviewed_at") == user_before.get("last_reviewed_at")
        assert "last_app_grade" not in user
        state = await core.study_use_cases.current(USER)
        assert state.card.delivery_id == card.delivery_id and state.undo_available is False

    async def test_the_card_can_be_graded_again_and_undone_only_once(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        await core.study_use_cases.undo(USER)

        again = await core.study_use_cases.grade(USER, expression_id, 5, "forward", delivery_id=card.delivery_id)
        assert again == Graded()
        assert (await _expr(cols, expression_id))["reps"] == 1

        await core.study_use_cases.undo(USER)
        assert await core.study_use_cases.undo(USER) == NothingToUndo()

    async def test_nothing_to_undo_without_an_app_grade(self, setup):
        core, _, _ = setup

        assert await core.study_use_cases.undo(USER) == NothingToUndo()

    async def test_after_the_card_was_sent_again_there_is_nothing_to_undo(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        await core.expression_service.update_expression_sent(expression_id, 999, user_id=USER)

        assert await core.study_use_cases.undo(USER) == NothingToUndo()

        expression = await _expr(cols, expression_id)
        assert expression["reps"] == 1 and expression["pending_message_id"] == 999
        assert "last_app_grade" not in await _user(cols)

    async def test_after_the_bot_graded_it_there_is_nothing_to_undo(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        await core.expression_service.update_expression_sent(expression_id, 555, user_id=USER)
        await core.review_use_cases.grade(USER, expression_id, 3, "forward", message_id=555)

        assert await core.study_use_cases.undo(USER) == NothingToUndo()

        assert (await _expr(cols, expression_id))["reps"] == 2

    async def test_not_after_an_hour(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        await cols["users"].update_one({"user_id": str(USER)}, {"$set": {
            "last_app_grade.graded_at": datetime.now(timezone.utc) - timedelta(minutes=61)}})

        assert (await core.study_use_cases.current(USER)).undo_available is False
        assert await core.study_use_cases.undo(USER) == NothingToUndo()
        assert (await _expr(cols, expression_id))["reps"] == 1

    async def test_undoing_a_reverse_grade_removes_the_reverse_stats_it_created(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)

        await core.study_use_cases.grade(USER, expression_id, 4, "reverse", delivery_id=card.delivery_id)
        assert (await _expr(cols, expression_id))["reverse_stats"]["reps"] == 1
        result = await core.study_use_cases.undo(USER)

        assert isinstance(result, Undone) and result.card.direction == "reverse"
        expression = await _expr(cols, expression_id)
        assert "reverse_stats" not in expression and expression["pending_message_id"] == card.delivery_id

    async def test_usage_is_not_refunded(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)

        await core.study_use_cases.undo(USER)

        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 1


class TestRefresh:

    async def test_replaces_the_section_and_costs_one_card(self, setup):
        core, cols, _ = setup
        card = await _delivered(core)

        result = await core.study_use_cases.refresh_section(USER, card.delivery_id, "definition")

        assert isinstance(result, Refreshed)
        assert result.card.card.learning_definition == "spostarsi da un posto a un altro"
        assert result.card.card.learning_example == card.card.learning_example
        assert [t.text for t in result.card.card.translations] == [t.text for t in card.card.translations]
        assert (await core.study_use_cases.current(USER)).card.card.learning_definition == "spostarsi da un posto a un altro"
        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 2

    async def test_translations_keep_their_labels(self, setup):
        core, _, _ = setup
        card = await _delivered(core)

        result = await core.study_use_cases.refresh_section(USER, card.delivery_id, "translations")

        assert [t.label for t in result.card.card.translations] == [t.label for t in card.card.translations]
        assert result.card.card.translations[0].text == "to head"

    async def test_after_the_card_was_graded_nothing_changes_and_nothing_is_charged(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)
        before = await _expr(cols, expression_id)

        result = await core.study_use_cases.refresh_section(USER, card.delivery_id, "example")

        assert result == NotPending()
        assert core.llm_service.section_calls == []
        assert (await _expr(cols, expression_id))["last_card"] == before["last_card"]
        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 1

    async def test_a_grade_during_generation_wins_and_the_card_stays_as_it_was(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        before = (await _expr(cols, expression_id))["last_card"]

        async def grade_meanwhile(_section):
            await core.study_use_cases.grade(USER, expression_id, 4, "forward", delivery_id=card.delivery_id)

        core.llm_service.during_section = grade_meanwhile

        result = await core.study_use_cases.refresh_section(USER, card.delivery_id, "definition")

        assert result == NotPending()
        assert (await _expr(cols, expression_id))["last_card"] == before
        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 1

    async def test_a_failed_generation_leaves_the_card_and_costs_nothing(self, setup):
        core, cols, expression_id = setup
        card = await _delivered(core)
        before = (await _expr(cols, expression_id))["last_card"]
        core.llm_service.fail_sections = True

        assert await core.study_use_cases.refresh_section(USER, card.delivery_id, "example") == GenerationFailed()

        assert (await _expr(cols, expression_id))["last_card"] == before
        assert (await _user(cols))["consumption"]["system_api"]["cards_generated"] == 1

    async def test_another_delivery_id_is_not_pending(self, setup):
        core, _, _ = setup
        await _delivered(core)

        assert await core.study_use_cases.refresh_section(USER, -1, "example") == NotPending()

    async def test_over_quota_is_a_quota_result_without_calling_the_llm(self, setup):
        core, cols, _ = setup
        card = await _delivered(core)
        await cols["users"].update_one({"user_id": str(USER)}, {"$set": {"consumption.system_api.credits_used": 20}})

        assert isinstance(await core.study_use_cases.refresh_section(USER, card.delivery_id, "example"), QuotaExceeded)
        assert core.llm_service.section_calls == []


class TestExpressionQueries:

    async def test_list_page_is_newest_first_and_cursor_paged(self, study_core, mongo_cols):
        for value in ("a1", "b2", "c3", "d4", "e5"):
            await add_word(mongo_cols, USER, value)
        await add_word(mongo_cols, OTHER, "other")
        expressions = study_core.expression_service

        first = await expressions.list_page(USER, limit=2)
        second = await expressions.list_page(USER, limit=2, cursor=first.next_cursor)
        third = await expressions.list_page(USER, limit=2, cursor=second.next_cursor)

        assert [e.value for e in first.items] == ["e5", "d4"]
        assert [e.value for e in second.items] == ["c3", "b2"]
        assert [e.value for e in third.items] == ["a1"]
        assert third.next_cursor is None and first.next_cursor is not None

    async def test_an_exact_last_page_has_no_cursor(self, study_core, mongo_cols):
        for value in ("a1", "b2"):
            await add_word(mongo_cols, USER, value)

        page = await study_core.expression_service.list_page(USER, limit=2)

        assert len(page.items) == 2 and page.next_cursor is None

    async def test_search_is_case_insensitive_unpaged_and_per_user(self, study_core, mongo_cols):
        for value in ("Andare", "mandare", "venire"):
            await add_word(mongo_cols, USER, value)
        await add_word(mongo_cols, OTHER, "andiamo")

        page = await study_core.expression_service.list_page(USER, limit=1, query="AND")

        assert [e.value for e in page.items] == ["mandare"]
        assert page.next_cursor is None

    async def test_a_foreign_cursor_is_refused(self, study_core):
        with pytest.raises(InvalidCursor):
            await study_core.expression_service.list_page(USER, limit=5, cursor="nope")

    async def test_count_words_separates_total_from_ready(self, study_core, mongo_cols):
        await add_word(mongo_cols, USER, "ready")
        await add_word(mongo_cols, USER, "resting", last_activity_at=datetime.now(timezone.utc))
        await add_word(mongo_cols, OTHER, "other")

        counts = await study_core.expression_service.count_words(USER)

        assert (counts.total, counts.ready) == (2, 1)

    async def test_still_due_and_get_expression_are_per_user(self, study_core, mongo_cols):
        expression_id = await add_word(mongo_cols, USER, "ready")
        expressions = study_core.expression_service

        assert await expressions.still_due(USER, expression_id) is True
        assert await expressions.still_due(OTHER, expression_id) is False
        assert await expressions.still_due(USER, "nope") is False
        assert await expressions.get_expression(OTHER, expression_id) is None
        assert await expressions.get_expression(USER, "nope") is None
        assert (await expressions.get_expression(USER, expression_id)).value == "ready"

    async def test_writes_scoped_to_a_user_do_not_reach_another_users_card(self, study_core, mongo_cols):
        expression_id = await add_word(mongo_cols, USER, "ready")
        expressions = study_core.expression_service

        await expressions.update_expression_sent(expression_id, -9, user_id=OTHER)

        assert (await _expr(mongo_cols, expression_id)).get("pending_message_id") is None

    async def test_collection_detail_and_list_through_the_use_case(self, study_core, mongo_cols):
        await add_user(mongo_cols, USER)
        expression_id = await add_word(mongo_cols, USER, "andare", reps=2, lapses=1,
                                       reverse_stats={"reps": 3, "lapses": 1})
        collection = study_core.collection_use_cases

        page = await collection.list_page(USER, limit=10)
        detail = await collection.detail(USER, expression_id)

        assert isinstance(page, ItemPage) and (page.items[0].reps, page.items[0].lapses) == (5, 2)
        assert detail.card is None and detail.generated_at is None
        assert await collection.detail(OTHER, expression_id) == NotFound()
        assert await collection.detail(USER, "nope") == NotFound()
        assert await collection.list_page(USER, query="a") == QueryTooShort()
        assert await collection.list_page(USER, cursor="nope") == BadCursor()
