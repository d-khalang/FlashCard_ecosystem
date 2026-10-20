"""
Unit tests for ReviewUseCases: the review contract, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.review import (
    CardNotFound, Graded, NoCandidate, QuotaExceeded, ReviewReady, ReviewUseCases,
)
from flashcard.schemas.expression import MAX_GRADE, MIN_GRADE
from tests.helpers import TEST_LANGUAGE
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier


EXPRESSION_ID = "65f000000000000000000001"


def _user(**overrides) -> UserDB:
    fields = {"user_id": "111", "primary_language": "en", "secondary_language": None,
              "target_level": "B1", "tier": UserTier.normal}
    fields.update(overrides)
    return UserDB(**fields)


def _use_cases(*, candidate=None, user=None, can_generate=True, card_limit=10):
    expressions = MagicMock()
    expressions.get_review_candidate = AsyncMock(return_value=candidate)
    expressions.update_expression_sent = AsyncMock()
    expressions.grade_expression = AsyncMock(return_value={"value": "andare"})

    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or _user())
    users.can_generate_card = MagicMock(return_value=can_generate)
    users.card_limit = MagicMock(return_value=card_limit)
    users.advance_onboarding = AsyncMock(return_value=True)

    consumption = MagicMock()
    consumption.increment = AsyncMock()

    llm = MagicMock()
    llm.generate_expression_card = AsyncMock(return_value="CARD")

    use_cases = ReviewUseCases(review_state=AsyncMock(), expression_service=expressions, user_service=users,
                               consumption_service=consumption, llm_service=llm,
                               user_defaults=TEST_LANGUAGE.user_defaults)
    return use_cases, expressions, users, consumption, llm


def _candidate(direction="forward", **doc):
    return {"doc": {"_id": EXPRESSION_ID, "value": "andare", **doc}, "direction": direction}


class TestPrepareNext:

    async def test_no_candidate_skips_generation(self):
        use_cases, _, _, _, llm = _use_cases(candidate=None)

        assert await use_cases.prepare_next(111) == NoCandidate()
        llm.generate_expression_card.assert_not_awaited()

    @pytest.mark.parametrize("mode", ["standard", "dual"])
    async def test_candidate_uses_the_users_review_mode(self, mode):
        use_cases, expressions, _, _, _ = _use_cases(candidate=_candidate(), user=_user(review_mode=mode))

        await use_cases.prepare_next(111)

        expressions.get_review_candidate.assert_awaited_once_with(111, mode)

    async def test_quota_exceeded_reports_tier_and_card_limit(self):
        user = _user(tier=UserTier.digi)
        use_cases, _, users, _, llm = _use_cases(candidate=_candidate(), user=user,
                                                 can_generate=False, card_limit=40)

        assert await use_cases.prepare_next(111) == QuotaExceeded(tier="digi", limit=40)
        users.card_limit.assert_called_once_with(user)
        llm.generate_expression_card.assert_not_awaited()

    async def test_ready_carries_everything_the_caller_needs(self):
        use_cases, *_ = _use_cases(candidate=_candidate(direction="reverse"))

        assert await use_cases.prepare_next(111) == ReviewReady(
            expression_id=EXPRESSION_ID, value="andare", direction="reverse",
            card="CARD", uses_own_key=False)

    async def test_missing_direction_defaults_to_forward(self):
        use_cases, *_ = _use_cases(candidate={"doc": {"_id": EXPRESSION_ID, "value": "andare"}})

        assert (await use_cases.prepare_next(111)).direction == "forward"

    async def test_object_id_is_returned_as_string(self):
        from bson import ObjectId
        use_cases, *_ = _use_cases(candidate={"doc": {"_id": ObjectId(EXPRESSION_ID), "value": "andare"}})

        assert (await use_cases.prepare_next(111)).expression_id == EXPRESSION_ID

    async def test_fetches_user_when_not_given(self):
        use_cases, _, users, _, _ = _use_cases(candidate=_candidate())

        await use_cases.prepare_next(111)
        users.get_user.assert_awaited_once_with(111)

    async def test_uses_given_user_without_fetching(self):
        given = _user(target_level="C1")
        use_cases, _, users, _, llm = _use_cases(candidate=_candidate())

        await use_cases.prepare_next("111", user=given)
        users.get_user.assert_not_awaited()
        assert llm.generate_expression_card.await_args.kwargs["level"] == "C1"

    async def test_own_api_key_is_reported_and_used_for_quota(self):
        user = _user(api_config=UserAPIConfig(api_key="test"))
        use_cases, _, users, _, _ = _use_cases(candidate=_candidate(), user=user)

        result = await use_cases.prepare_next(111)
        assert result.uses_own_key is True
        users.can_generate_card.assert_called_once_with(user, uses_own_key=True)

    async def test_generation_uses_user_preferences(self):
        user = _user(primary_language="fa", secondary_language="en", target_level="A2")
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate(), user=user)

        await use_cases.prepare_next(111)
        llm.generate_expression_card.assert_awaited_once_with(
            raw="andare", level="A2", lang1_code="fa", lang2_code="en",
            lang1_label="🇮🇷", lang2_label="🇬🇧")

    async def test_generation_falls_back_to_default_level_and_language(self):
        user = _user().model_copy(update={"target_level": None, "primary_language": None})
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate(), user=user)

        await use_cases.prepare_next(111)
        kwargs = llm.generate_expression_card.await_args.kwargs
        assert kwargs["level"] == TEST_LANGUAGE.user_defaults.target_level
        assert kwargs["lang1_code"] == TEST_LANGUAGE.user_defaults.primary_language

    async def test_generation_failure_propagates(self):
        use_cases, _, _, consumption, llm = _use_cases(candidate=_candidate())
        llm.generate_expression_card.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            await use_cases.prepare_next(111)
        consumption.increment.assert_not_awaited()

    async def test_prepare_writes_nothing(self):
        use_cases, expressions, users, consumption, _ = _use_cases(candidate=_candidate())

        await use_cases.prepare_next(111)
        expressions.update_expression_sent.assert_not_awaited()
        use_cases.review_state.mark_pending.assert_not_awaited()
        consumption.increment.assert_not_awaited()


class TestMarkSent:

    @pytest.mark.parametrize("uses_own_key", [False, True])
    async def test_records_message_push_and_usage(self, uses_own_key):
        use_cases, expressions, users, consumption, _ = _use_cases()
        ready = ReviewReady(expression_id=EXPRESSION_ID, value="andare", direction="forward",
                            card="CARD", uses_own_key=uses_own_key)

        await use_cases.mark_sent(111, ready, 42)

        expressions.update_expression_sent.assert_awaited_once_with(EXPRESSION_ID, 42)
        use_cases.review_state.mark_pending.assert_awaited_once_with(111)
        consumption.increment.assert_awaited_once_with(111, "cards_generated", uses_own_key=uses_own_key)


class TestGrade:

    async def test_graded_passes_grade_and_direction_through(self):
        use_cases, expressions, *_ = _use_cases()

        assert await use_cases.grade(111, EXPRESSION_ID, 3, "reverse") == Graded()
        expressions.grade_expression.assert_awaited_once_with(111, EXPRESSION_ID, 3, "reverse")

    async def test_missing_card_is_reported(self):
        use_cases, expressions, *_ = _use_cases()
        expressions.grade_expression.return_value = None

        assert await use_cases.grade(111, EXPRESSION_ID, 3, "forward") == CardNotFound()

    async def test_grade_does_not_touch_onboarding(self):
        use_cases, _, users, _, _ = _use_cases()

        await use_cases.grade(111, EXPRESSION_ID, 3, "forward")
        users.get_user.assert_not_awaited()
        users.advance_onboarding.assert_not_awaited()


    @pytest.mark.parametrize("grade", [MIN_GRADE, MAX_GRADE])
    async def test_boundary_grades_are_accepted(self, grade):
        use_cases, *_ = _use_cases()

        assert await use_cases.grade(111, EXPRESSION_ID, grade, "forward") == Graded()

    # The grading rules live in ExpressionService, so these run against a real one.
    def _with_real_expressions(self):
        from bson import ObjectId
        from flashcard.services.expression import ExpressionService
        from tests.integration.helpers import make_cols
        expression_id = ObjectId()
        cols = make_cols(expressions=[{"_id": expression_id, "user_id": "111", "value": "andare",
                                       "created_at": "2000-01-01T00:00:00Z", "status": "active"}])
        use_cases = ReviewUseCases(review_state=AsyncMock(), user_service=MagicMock(),
                                   expression_service=ExpressionService(expressions=cols["expression"]),
                                   consumption_service=MagicMock(), llm_service=MagicMock(),
                                   user_defaults=TEST_LANGUAGE.user_defaults)
        return use_cases, str(expression_id), cols["expression"].docs

    @pytest.mark.parametrize("grade", [-1, 6, 9, True, 2.5, "3"])
    async def test_invalid_grade_raises_without_writing(self, grade):
        use_cases, expression_id, docs = self._with_real_expressions()
        before = [dict(doc) for doc in docs]

        with pytest.raises(ValueError, match="grade"):
            await use_cases.grade(111, expression_id, grade, "forward")
        assert docs == before
        use_cases.review_state.record_reviewed.assert_not_awaited()

    @pytest.mark.parametrize("direction", ["fwd", "rev", "sideways", ""])
    async def test_unknown_direction_raises_without_writing(self, direction):
        use_cases, expression_id, docs = self._with_real_expressions()
        before = [dict(doc) for doc in docs]

        with pytest.raises(ValueError, match="direction"):
            await use_cases.grade(111, expression_id, 3, direction)
        assert docs == before
        use_cases.review_state.record_reviewed.assert_not_awaited()


class TestClaimFirstReviewTip:

    async def test_claimed_at_step_one_and_onboarding_advances(self):
        use_cases, _, users, _, _ = _use_cases(user=_user(onboarding_step=1))

        assert await use_cases.claim_first_review_tip(111) is True
        users.advance_onboarding.assert_awaited_once_with(111, 1)

    @pytest.mark.parametrize("step", [0, 2])
    async def test_not_claimed_at_other_steps(self, step):
        use_cases, _, users, _, _ = _use_cases(user=_user(onboarding_step=step))

        assert await use_cases.claim_first_review_tip(111) is False
        users.advance_onboarding.assert_not_awaited()

    async def test_not_claimed_when_a_concurrent_grade_advanced_first(self):
        use_cases, _, users, _, _ = _use_cases(user=_user(onboarding_step=1))
        users.advance_onboarding.return_value = False

        assert await use_cases.claim_first_review_tip(111) is False


class TestReviewStateShadow:
    """current_review is written alongside the legacy fields; its failure never breaks a review."""

    def _ready(self):
        return ReviewReady(expression_id=EXPRESSION_ID, value="andare", direction="reverse",
                           card="CARD", uses_own_key=False)

    async def test_mark_sent_records_the_current_review(self):
        use_cases, _, _, _, _ = _use_cases()

        await use_cases.mark_sent(111, self._ready(), 777)

        use_cases.review_state.record_sent.assert_awaited_once_with(111, EXPRESSION_ID, "reverse", 777)

    async def test_mark_sent_survives_a_review_state_failure(self):
        use_cases, expressions, users, consumption, _ = _use_cases()
        use_cases.review_state.record_sent.side_effect = RuntimeError("mongo down")

        await use_cases.mark_sent(111, self._ready(), 777)

        expressions.update_expression_sent.assert_awaited_once()
        use_cases.review_state.mark_pending.assert_awaited_once()
        consumption.increment.assert_awaited_once()

    async def test_grade_records_the_review(self):
        use_cases, _, _, _, _ = _use_cases()

        await use_cases.grade(111, EXPRESSION_ID, 4, "forward")

        use_cases.review_state.record_reviewed.assert_awaited_once_with(111)

    async def test_missing_card_records_no_review(self):
        use_cases, expressions, _, _, _ = _use_cases()
        expressions.grade_expression.return_value = None

        await use_cases.grade(111, EXPRESSION_ID, 4, "forward")

        use_cases.review_state.record_reviewed.assert_not_awaited()

    async def test_grade_clears_the_current_review(self):
        use_cases, _, _, _, _ = _use_cases()

        assert await use_cases.grade(111, EXPRESSION_ID, 4, "forward") == Graded()
        use_cases.review_state.record_graded.assert_awaited_once_with(111, EXPRESSION_ID, "forward")

    async def test_grade_survives_a_review_state_failure(self):
        use_cases, _, _, _, _ = _use_cases()
        use_cases.review_state.record_graded.side_effect = RuntimeError("mongo down")

        assert await use_cases.grade(111, EXPRESSION_ID, 4, "forward") == Graded()

    async def test_missing_card_leaves_review_state_alone(self):
        use_cases, expressions, _, _, _ = _use_cases()
        expressions.grade_expression.return_value = None

        assert await use_cases.grade(111, EXPRESSION_ID, 4, "forward") == CardNotFound()
        use_cases.review_state.record_graded.assert_not_awaited()
