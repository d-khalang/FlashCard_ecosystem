"""
Unit tests for ReviewUseCases: the review contract, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.review import (
    CardGenerationFailed, CardNotFound, Graded, NoCandidate, QuotaExceeded, ReviewReady, ReviewUseCases,
)
from flashcard.schemas.expression import (
    MAX_GRADE, MIN_GRADE, CardSettings, Expression, ExpressionCard, ReviewCandidate, StoredCard, TranslationLine,
)
from flashcard.app.quota import Allowed
from tests.helpers import make_quota, make_user
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier


EXPRESSION_ID = "65f000000000000000000001"
CARD = ExpressionCard(success=True, norm="andare", learning_definition="muoversi",
                      translations=[TranslationLine(label="🇬🇧 EN", text="to go")],
                      learning_example="Vado a casa.", note=None, suggestions=[])
SETTINGS = CardSettings(level="B1", primary_language="en", secondary_language=None)


def _user(**overrides) -> UserDB:
    fields = {"user_id": 111, "primary_language": "en", "secondary_language": None,
              "target_level": "B1", "tier": UserTier.normal}
    fields.update(overrides)
    return make_user(**fields)


def _use_cases(*, candidate=None, user=None, exceeded=None):
    expressions = MagicMock()
    expressions.get_review_candidate = AsyncMock(return_value=candidate)
    expressions.update_expression_sent = AsyncMock()
    expressions.grade_expression = AsyncMock(return_value=True)

    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or _user())
    users.advance_onboarding = AsyncMock(return_value=True)

    consumption = MagicMock()
    consumption.increment = AsyncMock()

    llm = MagicMock()
    llm.generate_expression_card = AsyncMock(return_value=CARD)

    use_cases = ReviewUseCases(review_state=AsyncMock(), expression_service=expressions, user_service=users,
                               quota=make_quota(consumption, exceeded), llm_service=llm)
    return use_cases, expressions, users, consumption, llm


def _candidate(direction="forward", **doc):
    """What ExpressionService.get_review_candidate returns, read from a stored document."""
    expression = Expression.model_validate({"_id": EXPRESSION_ID, "user_id": "111", "value": "andare", **doc})
    return ReviewCandidate(expression=expression, direction=direction)


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
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate(), user=user,
                                             exceeded=QuotaExceeded(tier="digi", limit=40))

        assert await use_cases.prepare_next(111) == QuotaExceeded(tier="digi", limit=40)
        llm.generate_expression_card.assert_not_awaited()

    async def test_ready_carries_everything_the_caller_needs(self):
        use_cases, *_ = _use_cases(candidate=_candidate(direction="reverse"))

        assert await use_cases.prepare_next(111) == ReviewReady(
            expression_id=EXPRESSION_ID, value="andare", direction="reverse",
            card=CARD, settings=SETTINGS, quota=Allowed(uses_own_key=False))

    async def test_object_id_is_returned_as_string(self):
        from bson import ObjectId
        use_cases, *_ = _use_cases(candidate=_candidate(_id=ObjectId(EXPRESSION_ID)))

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
        use_cases, *_ = _use_cases(candidate=_candidate(), user=user)

        result = await use_cases.prepare_next(111)
        assert result.quota == Allowed(uses_own_key=True)

    async def test_generation_uses_user_preferences(self):
        user = _user(primary_language="fa", secondary_language="en", target_level="A2")
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate(), user=user)

        await use_cases.prepare_next(111)
        llm.generate_expression_card.assert_awaited_once_with(
            raw="andare", level="A2", lang1_code="fa", lang2_code="en",
            lang1_label="🇮🇷", lang2_label="🇬🇧", on_fallback=None)

    async def test_no_secondary_language_passes_no_label(self):
        """Same request as card creation (both use app.cards.generate_card)."""
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate(), user=_user(secondary_language="none"))

        await use_cases.prepare_next(111)
        kwargs = llm.generate_expression_card.await_args.kwargs
        assert kwargs["lang2_code"] is None
        assert kwargs["lang2_label"] is None

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
                            card=CARD, settings=SETTINGS, quota=Allowed(uses_own_key=uses_own_key))

        await use_cases.mark_sent(111, ready, 42)

        expressions.update_expression_sent.assert_awaited_once()
        assert expressions.update_expression_sent.await_args.args == (EXPRESSION_ID, 42)
        use_cases.review_state.mark_pending.assert_awaited_once_with(111)
        consumption.increment.assert_awaited_once_with(111, "cards_generated", uses_own_key=uses_own_key)


class TestStoredCardFallback:
    """The latest delivered card is the fallback when generation fails."""

    STORED = StoredCard(card=CARD, settings=SETTINGS, generated_at="2026-10-01T10:00:00Z")
    UNCLEAR = ExpressionCard(success=False, norm="andare", learning_definition=None, translations=[],
                             learning_example=None, note="Not clear", suggestions=[])

    def _with_stored(self, raw=None):
        return _candidate(last_card=raw if raw is not None else self.STORED.model_dump(mode="json"))

    async def test_provider_failure_returns_the_stored_card(self):
        use_cases, _, _, _, llm = _use_cases(candidate=self._with_stored())
        llm.generate_expression_card.side_effect = RuntimeError("all providers down")

        assert await use_cases.prepare_next(111) == ReviewReady(
            expression_id=EXPRESSION_ID, value="andare", direction="forward", card=CARD,
            settings=SETTINGS, quota=None, older_settings=False)

    async def test_unclear_card_returns_the_stored_card(self):
        use_cases, _, _, _, llm = _use_cases(candidate=self._with_stored())
        llm.generate_expression_card.return_value = self.UNCLEAR

        result = await use_cases.prepare_next(111)
        assert result.from_storage is True
        assert result.card == CARD

    async def test_unclear_card_without_stored_card_raises(self):
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate())
        llm.generate_expression_card.return_value = self.UNCLEAR

        with pytest.raises(CardGenerationFailed):
            await use_cases.prepare_next(111)

    @pytest.mark.parametrize("change", [{"target_level": "C1"}, {"primary_language": "fa"},
                                        {"secondary_language": "fa"}])
    async def test_changed_settings_are_flagged(self, change):
        use_cases, _, _, _, llm = _use_cases(candidate=self._with_stored(), user=_user(**change))
        llm.generate_expression_card.side_effect = RuntimeError("all providers down")

        assert (await use_cases.prepare_next(111)).older_settings is True

    async def test_turned_off_secondary_language_matches_an_unset_one(self):
        # SETTINGS has no secondary language; older documents store "off" as "none".
        use_cases, _, _, _, llm = _use_cases(candidate=self._with_stored(), user=_user(secondary_language="none"))
        llm.generate_expression_card.side_effect = RuntimeError("all providers down")

        assert (await use_cases.prepare_next(111)).older_settings is False
        assert llm.generate_expression_card.await_args.kwargs["lang2_code"] is None

    async def test_unreadable_stored_card_is_ignored(self):
        use_cases, _, _, _, llm = _use_cases(candidate=self._with_stored(raw={"card": "broken"}))
        llm.generate_expression_card.side_effect = RuntimeError("all providers down")

        with pytest.raises(RuntimeError, match="all providers down"):
            await use_cases.prepare_next(111)

    async def test_over_quota_returns_the_stored_card_without_generating(self):
        use_cases, _, _, _, llm = _use_cases(candidate=self._with_stored(),
                                             exceeded=QuotaExceeded(tier="normal", limit=10))

        assert await use_cases.prepare_next(111) == ReviewReady(
            expression_id=EXPRESSION_ID, value="andare", direction="forward", card=CARD,
            settings=SETTINGS, quota=None, older_settings=False)
        llm.generate_expression_card.assert_not_awaited()

    async def test_over_quota_without_stored_card_reports_quota(self):
        use_cases, _, _, _, llm = _use_cases(candidate=_candidate(),
                                             exceeded=QuotaExceeded(tier="normal", limit=10))

        assert await use_cases.prepare_next(111) == QuotaExceeded(tier="normal", limit=10)
        llm.generate_expression_card.assert_not_awaited()

    async def test_mark_sent_stores_a_fresh_card(self):
        use_cases, expressions, _, consumption, _ = _use_cases()
        ready = ReviewReady(expression_id=EXPRESSION_ID, value="andare", direction="forward",
                            card=CARD, settings=SETTINGS, quota=Allowed(uses_own_key=False))

        await use_cases.mark_sent(111, ready, 42)

        stored = expressions.update_expression_sent.await_args.kwargs["last_card"]
        assert (stored.card, stored.settings) == (CARD, SETTINGS)
        consumption.increment.assert_awaited_once()

    async def test_mark_sent_neither_stores_nor_counts_a_stored_card(self):
        use_cases, expressions, _, consumption, _ = _use_cases()
        ready = ReviewReady(expression_id=EXPRESSION_ID, value="andare", direction="forward",
                            card=CARD, settings=SETTINGS, quota=None)

        await use_cases.mark_sent(111, ready, 42)

        expressions.update_expression_sent.assert_awaited_once_with(EXPRESSION_ID, 42, last_card=None)
        use_cases.review_state.mark_pending.assert_awaited_once_with(111)
        consumption.increment.assert_not_awaited()


class TestGrade:

    async def test_graded_passes_grade_and_direction_through(self):
        use_cases, expressions, *_ = _use_cases()

        assert await use_cases.grade(111, EXPRESSION_ID, 3, "reverse") == Graded()
        expressions.grade_expression.assert_awaited_once_with(111, EXPRESSION_ID, 3, "reverse")

    async def test_missing_card_is_reported(self):
        use_cases, expressions, *_ = _use_cases()
        expressions.grade_expression.return_value = False

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
                                   quota=MagicMock(), llm_service=MagicMock())
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
                           card=CARD, settings=SETTINGS, quota=Allowed(uses_own_key=False))

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
        expressions.grade_expression.return_value = False

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
        expressions.grade_expression.return_value = False

        assert await use_cases.grade(111, EXPRESSION_ID, 4, "forward") == CardNotFound()
        use_cases.review_state.record_graded.assert_not_awaited()
