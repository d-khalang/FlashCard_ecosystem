"""
Unit tests for StudyUseCases with its collaborators mocked: what it asks of each, in which order.
Compare-and-set behavior is covered against a real MongoDB in tests/integration/test_study_mongo.py.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.quota import Allowed, QuotaExceeded
from flashcard.app.review import CardNotFound, Graded, NoCandidate, NotPending, ReviewReady
from flashcard.app.study import (
    MAX_DELIVERY_ID, Delivered, GenerationFailed, NothingToUndo, StudyUseCases, Undone, new_delivery_id,
)
from flashcard.schemas.expression import CardSection, CardSettings, Expression, StoredCard
from flashcard.schemas.user import CurrentReview, LastAppGrade
from tests.helpers import make_quota, make_user
from tests.integration.study_helpers import make_card

EXPRESSION_ID = "65f000000000000000000001"
SETTINGS = CardSettings(level="A2", primary_language="en", secondary_language=None)
NOW = datetime.now(timezone.utc)


def _ready(quota=Allowed(uses_own_key=False)) -> ReviewReady:
    return ReviewReady(expression_id=EXPRESSION_ID, value="andare", direction="forward", card=make_card(),
                       settings=SETTINGS, quota=quota)


def _expression(**fields) -> Expression:
    doc = {"_id": EXPRESSION_ID, "user_id": "42", "value": "andare", "created_at": NOW,
           "last_card": StoredCard(card=make_card(), settings=SETTINGS, generated_at=NOW).model_dump(), **fields}
    return Expression.model_validate(doc)


def _build(user=None, expression=None, exceeded=None):
    review = MagicMock()
    review.prepare_next = AsyncMock(return_value=_ready())
    expressions = MagicMock()
    expressions.update_expression_sent = AsyncMock()
    expressions.get_expression = AsyncMock(return_value=expression)
    expressions.still_due = AsyncMock(return_value=True)
    expressions.check_gradable = AsyncMock(return_value="pending")
    expressions.grade_expression = AsyncMock(return_value="graded")
    expressions.undo_grade = AsyncMock(return_value="undone")
    expressions.merge_card_section = AsyncMock(return_value=True)
    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or make_user(user_id=42))
    consumption = MagicMock()
    consumption.increment = AsyncMock()
    llm = MagicMock()
    llm.generate_card_section = AsyncMock(return_value=CardSection(definition="nuova", translations=[], example=None))
    state = MagicMock()
    for name in ("record_sent", "record_reviewed", "record_graded", "record_app_grade", "restore_after_undo",
                 "clear_app_grade", "mark_pending"):
        setattr(state, name, AsyncMock())
    study = StudyUseCases(review_use_cases=review, expression_service=expressions, user_service=users,
                          quota=make_quota(consumption, exceeded), llm_service=llm, review_state=state)
    return study, review, expressions, users, consumption, llm, state


class TestDeliveryId:

    def test_is_negative_and_within_javascripts_safe_integers(self):
        ids = {new_delivery_id() for _ in range(2000)}

        assert all(-MAX_DELIVERY_ID <= i <= -1 for i in ids)
        assert MAX_DELIVERY_ID == 2**53 - 1
        assert len(ids) > 1990  # random, not a counter


class TestNext:

    async def test_delivers_a_fresh_card_without_the_legacy_pause_flag(self):
        study, review, expressions, _, consumption, _, state = _build()

        result = await study.next(42)

        assert isinstance(result, Delivered) and result.card.delivery_id < 0
        args, kwargs = expressions.update_expression_sent.await_args
        assert args == (EXPRESSION_ID, result.card.delivery_id)
        assert kwargs["user_id"] == 42 and kwargs["last_card"].card == make_card()
        state.record_sent.assert_awaited_once_with(42, EXPRESSION_ID, "forward", result.card.delivery_id)
        state.mark_pending.assert_not_awaited()
        consumption.increment.assert_awaited_once()

    async def test_a_stored_card_is_neither_stored_again_nor_counted(self):
        study, review, expressions, _, consumption, _, _ = _build()
        review.prepare_next.return_value = _ready(quota=None)

        result = await study.next(42)

        assert result.card.from_storage is True
        assert expressions.update_expression_sent.await_args.kwargs["last_card"] is None
        consumption.increment.assert_not_awaited()

    @pytest.mark.parametrize("outcome", [NoCandidate(), QuotaExceeded(tier="normal", limit=10), GenerationFailed()])
    async def test_other_outcomes_are_returned_and_write_nothing(self, outcome):
        study, review, expressions, _, _, _, state = _build()
        review.prepare_next.return_value = outcome if not isinstance(outcome, GenerationFailed) else None
        if isinstance(outcome, GenerationFailed):
            review.prepare_next.side_effect = RuntimeError("down")

        assert await study.next(42) == outcome

        expressions.update_expression_sent.assert_not_awaited()
        state.record_sent.assert_not_awaited()

    async def test_resumes_the_waiting_card_instead_of_delivering(self):
        review_state = CurrentReview(expression_id=EXPRESSION_ID, direction="unknown", message_id=-9, sent_at=NOW)
        user = make_user(user_id=42, current_review=review_state)
        study, review, expressions, *_ = _build(user=user, expression=_expression(pending_message_id=-9))

        result = await study.next(42)

        assert result.card.delivery_id == -9 and result.card.direction == "forward"
        review.prepare_next.assert_not_awaited()
        expressions.update_expression_sent.assert_not_awaited()

    async def test_a_waiting_card_that_is_no_longer_pending_is_replaced(self):
        review_state = CurrentReview(expression_id=EXPRESSION_ID, direction="forward", message_id=-9, sent_at=NOW)
        user = make_user(user_id=42, current_review=review_state)
        study, review, *_ = _build(user=user, expression=_expression(pending_message_id=None))

        result = await study.next(42)

        assert result.card.delivery_id != -9
        review.prepare_next.assert_awaited_once()

    async def test_concurrent_calls_deliver_one_card(self):
        study, review, expressions, users, *_ = _build()
        delivered = []

        async def slow_prepare(user_id):
            await asyncio.sleep(0.02)
            return _ready()

        async def deliver(*args, **kwargs):
            delivered.append(args[1])

        review.prepare_next.side_effect = slow_prepare
        expressions.update_expression_sent.side_effect = deliver

        async def get_user(_):
            # What the database would say: the second caller sees the first one's delivery.
            if delivered:
                return make_user(user_id=42, current_review=CurrentReview(
                    expression_id=EXPRESSION_ID, direction="forward", message_id=delivered[0], sent_at=NOW))
            return make_user(user_id=42)

        users.get_user.side_effect = get_user
        expressions.get_expression.side_effect = lambda *_: _expression(pending_message_id=delivered[0])

        first, second = await asyncio.gather(study.next(42), study.next(42))

        assert first.card.delivery_id == second.card.delivery_id == delivered[0]
        assert review.prepare_next.await_count == 1 and len(delivered) == 1

    async def test_locks_are_per_user(self):
        study, review, *_ = _build()
        started = []

        async def slow(user_id):
            started.append(user_id)
            await asyncio.sleep(0.05)
            return _ready()

        review.prepare_next.side_effect = slow

        await asyncio.gather(study.next(1), study.next(2))

        assert sorted(started) == [1, 2]

    async def test_the_lock_table_does_not_grow(self):
        study, *_ = _build()

        for user_id in range(20):
            await study.next(user_id + 1)

        assert study._delivery_locks._entries == {}

    async def test_generation_is_limited_to_the_server_side_timeout(self, monkeypatch):
        from flashcard.app import study as module
        study, review, *_ = _build()
        monkeypatch.setattr(module, "GENERATION_TIMEOUT_SECONDS", 0.02)

        async def hang(*_):
            await asyncio.sleep(1)

        review.prepare_next.side_effect = hang

        assert await study.next(42) == GenerationFailed()


class TestPreparedCards:

    async def test_a_valid_prepared_card_is_used_and_generation_is_skipped(self):
        study, review, *_ = _build()

        async def take():
            return _ready()

        result = await study.next(42, take_prepared=take)

        assert isinstance(result, Delivered)
        review.prepare_next.assert_not_awaited()

    async def test_the_waiting_card_wins_and_the_slot_is_left_alone(self):
        review_state = CurrentReview(expression_id=EXPRESSION_ID, direction="forward", message_id=-9, sent_at=NOW)
        user = make_user(user_id=42, current_review=review_state)
        study, *_ = _build(user=user, expression=_expression(pending_message_id=-9))
        take = AsyncMock(return_value=_ready())

        await study.next(42, take_prepared=take)

        take.assert_not_awaited()

    @pytest.mark.parametrize("why", ["cooldown", "settings", "quota"])
    async def test_a_stale_prepared_card_is_discarded(self, why):
        study, review, expressions, users, *_ = _build(
            exceeded=QuotaExceeded(tier="normal", limit=10) if why == "quota" else None)
        if why == "cooldown":
            expressions.still_due.return_value = False
        if why == "settings":
            users.get_user.return_value = make_user(user_id=42, target_level="C2")

        async def take():
            return _ready()

        await study.next(42, take_prepared=take)

        review.prepare_next.assert_awaited_once()

    async def test_a_prepared_stored_card_needs_only_to_be_due(self):
        study, review, *_ = _build(exceeded=QuotaExceeded(tier="normal", limit=10))

        async def take():
            return _ready(quota=None)

        result = await study.next(42, take_prepared=take)

        assert result.card.from_storage is True
        review.prepare_next.assert_not_awaited()


class TestGrade:

    async def test_grades_like_the_bot_does_and_keeps_undo_data(self):
        study, _, expressions, _, _, _, state = _build()
        order = []
        state.record_reviewed.side_effect = lambda *_: order.append("reviewed")
        expressions.grade_expression.side_effect = lambda *a, **k: order.append("card") or "graded"

        result = await study.grade(42, EXPRESSION_ID, 4, "forward", delivery_id=-7)

        assert result == Graded() and order == ["reviewed", "card"]  # the card write comes last
        expressions.check_gradable.assert_awaited_once_with(42, EXPRESSION_ID, 4, "forward", message_id=-7)
        expressions.grade_expression.assert_awaited_once_with(
            42, EXPRESSION_ID, 4, "forward", message_id=-7, keep_undo=True)
        saved = state.record_app_grade.await_args.args[1]
        assert (saved.expression_id, saved.delivery_id, saved.direction) == (EXPRESSION_ID, -7, "forward")

    async def test_the_undo_hint_uses_the_review_interval_before_this_grade(self):
        previous = NOW - timedelta(hours=3)
        review_state = CurrentReview(expression_id=EXPRESSION_ID, direction="forward", message_id=-7, sent_at=NOW)
        user = make_user(user_id=42, last_reviewed_at=previous, current_review=review_state)
        study, *_, state = _build(user=user)

        await study.grade(42, EXPRESSION_ID, 4, "forward", delivery_id=-7)

        saved = state.record_app_grade.await_args.args[1]
        assert saved.previous_reviewed_at == previous and saved.sent_at == NOW

    @pytest.mark.parametrize("bad_id", ["zzz", "", "12", None])
    async def test_a_malformed_expression_id_is_not_found_before_any_lookup(self, bad_id):
        study, _, expressions, *_ = _build()

        assert await study.grade(42, bad_id, 4, "forward", delivery_id=-7) == CardNotFound()

        expressions.check_gradable.assert_not_awaited()

    @pytest.mark.parametrize("check, expected", [("not_found", CardNotFound()), ("not_pending", NotPending())])
    async def test_a_failed_check_writes_nothing(self, check, expected):
        study, _, expressions, _, _, _, state = _build()
        expressions.check_gradable.return_value = check

        assert await study.grade(42, EXPRESSION_ID, 4, "forward", delivery_id=-7) == expected

        state.record_reviewed.assert_not_awaited()
        expressions.grade_expression.assert_not_awaited()

    async def test_losing_the_race_remembers_no_undo(self):
        study, _, expressions, _, _, _, state = _build()
        expressions.grade_expression.return_value = "not_pending"

        assert await study.grade(42, EXPRESSION_ID, 4, "forward", delivery_id=-7) == NotPending()

        state.record_app_grade.assert_not_awaited()

    async def test_failing_to_remember_undo_does_not_fail_the_grade(self):
        study, *_, state = _build()
        state.record_app_grade.side_effect = RuntimeError("db hiccup")

        assert await study.grade(42, EXPRESSION_ID, 4, "forward", delivery_id=-7) == Graded()

    async def test_an_invalid_grade_raises_from_the_service(self):
        study, _, expressions, *_ = _build()
        expressions.check_gradable.side_effect = ValueError("grade must be 0-5")

        with pytest.raises(ValueError):
            await study.grade(42, EXPRESSION_ID, 9, "forward", delivery_id=-7)


def _last_grade(**fields) -> LastAppGrade:
    return LastAppGrade(**{"expression_id": EXPRESSION_ID, "direction": "forward", "delivery_id": -7,
                           "previous_reviewed_at": None, "sent_at": NOW, "graded_at": NOW, **fields})


class TestUndo:

    async def test_restores_the_card_then_the_user_state(self):
        user = make_user(user_id=42, last_app_grade=_last_grade())
        study, _, expressions, _, _, _, state = _build(user=user, expression=_expression())

        result = await study.undo(42)

        assert isinstance(result, Undone) and result.card.delivery_id == -7
        expressions.undo_grade.assert_awaited_once_with(42, EXPRESSION_ID, -7)
        state.restore_after_undo.assert_awaited_once()
        state.clear_app_grade.assert_not_awaited()

    async def test_when_the_card_cannot_be_restored_the_hint_is_dropped(self):
        user = make_user(user_id=42, last_app_grade=_last_grade())
        study, _, expressions, _, _, _, state = _build(user=user, expression=_expression())
        expressions.undo_grade.return_value = "nothing_to_undo"

        assert await study.undo(42) == NothingToUndo()

        state.restore_after_undo.assert_not_awaited()
        state.clear_app_grade.assert_awaited_once_with(42, -7)

    async def test_nothing_without_a_hint_or_after_an_hour(self):
        for hint in (None, _last_grade(graded_at=NOW - timedelta(minutes=61))):
            study, _, expressions, *_ = _build(user=make_user(user_id=42, last_app_grade=hint),
                                               expression=_expression())

            assert await study.undo(42) == NothingToUndo()
            expressions.undo_grade.assert_not_awaited()

    async def test_the_current_state_says_whether_undo_is_available(self):
        study, *_ = _build(user=make_user(user_id=42, last_app_grade=_last_grade()))
        assert (await study.current(42)).undo_available is True
        study, *_ = _build(user=make_user(user_id=42))
        assert (await study.current(42)).undo_available is False


class TestRefresh:

    def _waiting(self):
        review_state = CurrentReview(expression_id=EXPRESSION_ID, direction="forward", message_id=-7, sent_at=NOW)
        return make_user(user_id=42, current_review=review_state), _expression(pending_message_id=-7)

    async def test_generates_merges_and_counts_one_card(self):
        user, expression = self._waiting()
        study, _, expressions, _, consumption, llm, _ = _build(user=user, expression=expression)

        result = await study.refresh_section(42, -7, "definition")

        assert result.card.delivery_id == -7
        assert llm.generate_card_section.await_args.args == ("definition",)
        expressions.merge_card_section.assert_awaited_once()
        assert expressions.merge_card_section.await_args.args[:4] == (42, EXPRESSION_ID, -7, "definition")
        consumption.increment.assert_awaited_once()

    async def test_losing_the_compare_and_set_costs_nothing(self):
        user, expression = self._waiting()
        study, _, expressions, _, consumption, *_ = _build(user=user, expression=expression)
        expressions.merge_card_section.return_value = False

        assert await study.refresh_section(42, -7, "example") == NotPending()

        consumption.increment.assert_not_awaited()

    async def test_only_the_pending_delivery_can_be_refreshed(self):
        user, expression = self._waiting()
        study, _, _, _, _, llm, _ = _build(user=user, expression=expression)

        assert await study.refresh_section(42, -8, "example") == NotPending()
        llm.generate_card_section.assert_not_awaited()

    async def test_a_failed_generation_changes_nothing(self):
        user, expression = self._waiting()
        study, _, expressions, _, consumption, llm, _ = _build(user=user, expression=expression)
        llm.generate_card_section.side_effect = ValueError("labels changed")

        assert await study.refresh_section(42, -7, "translations") == GenerationFailed()

        expressions.merge_card_section.assert_not_awaited()
        consumption.increment.assert_not_awaited()

    async def test_over_quota_does_not_call_the_llm(self):
        user, expression = self._waiting()
        study, _, _, _, _, llm, _ = _build(user=user, expression=expression,
                                           exceeded=QuotaExceeded(tier="normal", limit=10))

        assert isinstance(await study.refresh_section(42, -7, "example"), QuotaExceeded)
        llm.generate_card_section.assert_not_awaited()

    async def test_an_unknown_section_is_a_value_error(self):
        study, *_ = _build()

        with pytest.raises(ValueError):
            await study.refresh_section(42, -7, "everything")
