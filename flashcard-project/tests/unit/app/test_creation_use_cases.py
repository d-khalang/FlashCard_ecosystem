"""
Unit tests for CreationUseCases: the creation contract, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.creation import (
    AlreadySaved, CardReady, CreationUseCases, InvalidInput, Saved, Unclear,
)
from flashcard.app.quota import QuotaExceeded
from flashcard.schemas.expression import ExpressionCard, TranslationLine
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier
from flashcard.services.language_validation import LanguageValidationResult
from tests.helpers import make_quota, make_user


def _card(success=True) -> ExpressionCard:
    return ExpressionCard(success=success, norm="andare",
                          learning_definition="muoversi" if success else None,
                          translations=[TranslationLine(label="🇬🇧 EN", text="to go")] if success else [],
                          learning_example="Vado." if success else None,
                          note=None if success else "Not clear", suggestions=[])


def _user(**overrides) -> UserDB:
    fields = {"user_id": "222", "primary_language": "en", "secondary_language": None,
              "target_level": "B1", "tier": UserTier.normal}
    fields.update(overrides)
    return make_user(**fields)


def _use_cases(*, card=None, user=None, exceeded=None, validation=None, saved=True):
    expressions = MagicMock()
    expressions.add_expression = AsyncMock(return_value=saved)

    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or _user())
    users.advance_onboarding = AsyncMock(return_value=True)

    consumption = MagicMock()
    consumption.increment = AsyncMock()

    llm = MagicMock()
    llm.generate_expression_card = AsyncMock(return_value=card or _card())

    validator = None
    if validation is not None:
        validator = MagicMock()
        validator.validate_expression = AsyncMock(return_value=validation)

    use_cases = CreationUseCases(review_state=AsyncMock(), expression_service=expressions, user_service=users,
                                 quota=make_quota(consumption, exceeded), llm_service=llm,
                                 language_validator=validator)
    return use_cases, expressions, users, consumption, llm


class TestGenerate:

    async def test_ready_card_is_returned_and_counted(self):
        card = _card()
        use_cases, _, _, consumption, _ = _use_cases(card=card)

        assert await use_cases.generate(222, "andare") == CardReady(card=card)
        consumption.increment.assert_awaited_once_with(222, "cards_generated", uses_own_key=False)

    async def test_unclear_card_is_returned_and_not_counted(self):
        card = _card(success=False)
        use_cases, _, _, consumption, _ = _use_cases(card=card)

        assert await use_cases.generate(222, "xyz") == Unclear(card=card)
        consumption.increment.assert_not_awaited()

    async def test_invalid_input_returns_all_suggestions_and_skips_quota(self):
        use_cases, _, _, consumption, llm = _use_cases(
            validation=LanguageValidationResult(is_valid=False, suggestions=["a", "b", "c", "d"]))
        use_cases.quota.check = MagicMock()

        assert await use_cases.generate(222, "hello") == InvalidInput(suggestions=["a", "b", "c", "d"])
        use_cases.quota.check.assert_not_called()
        llm.generate_expression_card.assert_not_awaited()

    async def test_normalized_text_is_generated(self):
        use_cases, _, _, _, llm = _use_cases(
            validation=LanguageValidationResult(is_valid=True, normalized_text="andare"))

        await use_cases.generate(222, "  Andare ")
        assert llm.generate_expression_card.await_args.kwargs["raw"] == "andare"

    async def test_valid_without_normalization_keeps_raw_text(self):
        use_cases, _, _, _, llm = _use_cases(validation=LanguageValidationResult(is_valid=True))

        await use_cases.generate(222, "Andare")
        assert llm.generate_expression_card.await_args.kwargs["raw"] == "Andare"

    async def test_quota_exceeded_reports_tier_and_limit(self):
        user = _user(tier=UserTier.plus)
        use_cases, _, _, consumption, llm = _use_cases(user=user, exceeded=QuotaExceeded(tier="plus", limit=50))

        assert await use_cases.generate(222, "andare") == QuotaExceeded(tier="plus", limit=50)
        use_cases.quota.check.assert_called_once_with(user, "cards")
        llm.generate_expression_card.assert_not_awaited()
        consumption.increment.assert_not_awaited()

    async def test_own_api_key_is_used_for_quota_and_usage(self):
        user = _user(api_config=UserAPIConfig(api_key="test"))
        use_cases, _, _, consumption, _ = _use_cases(user=user)

        await use_cases.generate(222, "andare")
        consumption.increment.assert_awaited_once_with(222, "cards_generated", uses_own_key=True)

    async def test_generation_uses_preferences_and_fallback_notifier(self):
        user = _user(primary_language="fa", secondary_language="en", target_level="A2")
        use_cases, _, _, _, llm = _use_cases(user=user)
        notifier = AsyncMock()

        await use_cases.generate(222, "andare", on_fallback=notifier)
        llm.generate_expression_card.assert_awaited_once_with(
            raw="andare", level="A2", lang1_code="fa", lang2_code="en",
            lang1_label="🇮🇷", lang2_label="🇬🇧", on_fallback=notifier)

    async def test_no_secondary_language_sends_no_label(self):
        use_cases, _, _, _, llm = _use_cases()

        await use_cases.generate(222, "andare")
        assert llm.generate_expression_card.await_args.kwargs["lang2_label"] is None

    async def test_turned_off_secondary_language_asks_for_no_translation(self):
        use_cases, _, _, _, llm = _use_cases(user=_user(secondary_language="none"))

        await use_cases.generate(222, "andare")
        kwargs = llm.generate_expression_card.await_args.kwargs
        assert (kwargs["lang2_code"], kwargs["lang2_label"]) == (None, None)

    async def test_generation_failure_propagates_without_usage(self):
        use_cases, _, _, consumption, llm = _use_cases()
        llm.generate_expression_card.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            await use_cases.generate(222, "andare")
        consumption.increment.assert_not_awaited()


class TestSave:

    async def test_saved(self):
        use_cases, expressions, *_ = _use_cases(saved=True)

        assert await use_cases.save(222, "andare") == Saved()
        expressions.add_expression.assert_awaited_once_with(222, "andare")
        use_cases.review_state.clear_pending.assert_awaited_once_with(222)

    async def test_already_saved(self):
        use_cases, *_ = _use_cases(saved=False)

        assert await use_cases.save(222, "andare") == AlreadySaved()
        use_cases.review_state.clear_pending.assert_not_awaited()


class TestClaimFirstSaveTip:

    async def test_claimed_at_step_zero_and_onboarding_advances(self):
        use_cases, _, users, _, _ = _use_cases(user=_user(onboarding_step=0))

        assert await use_cases.claim_first_save_tip(222) is True
        users.advance_onboarding.assert_awaited_once_with(222, 0)

    @pytest.mark.parametrize("step", [1, 2])
    async def test_not_claimed_at_other_steps(self, step):
        use_cases, _, users, _, _ = _use_cases(user=_user(onboarding_step=step))

        assert await use_cases.claim_first_save_tip(222) is False
        users.advance_onboarding.assert_not_awaited()

    async def test_not_claimed_when_a_concurrent_save_advanced_first(self):
        use_cases, _, users, _, _ = _use_cases(user=_user(onboarding_step=0))
        users.advance_onboarding.return_value = False

        assert await use_cases.claim_first_save_tip(222) is False
