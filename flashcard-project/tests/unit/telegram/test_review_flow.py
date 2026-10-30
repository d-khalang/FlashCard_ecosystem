"""
Characterization tests for the review flow: /get, scheduled review and grading.

They pin current behavior at the entry points so the review logic can be moved
into a use-case layer without changing what users see or what is written.
"""
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import pytest

from flashcard.app.review import CardGenerationFailed, ReviewUseCases
from flashcard.schemas.expression import CardSettings, ExpressionCard, StoredCard, TranslationLine
from flashcard.app.quota import QuotaExceeded
from tests.helpers import TEST_LANGUAGE, make_quota, make_user
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier
from tests.helpers import TEST_I18N as i18n
from flashcard.telegram.handlers import review
from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.scheduler import scheduler


USER_ID = 111
EXPRESSION_ID = "65f000000000000000000001"
CANDIDATE = {"_id": EXPRESSION_ID, "value": "andare"}


def _user(**overrides) -> UserDB:
    fields = {"user_id": USER_ID, "primary_language": "en", "secondary_language": "fa",
              "target_level": "B1", "tier": UserTier.normal}
    fields.update(overrides)
    return make_user(**fields)


def _deps(*, candidate=CANDIDATE, direction="forward", user=None, can_generate=True, sent_message_id=42):
    user = user or _user()
    expression_service = MagicMock()
    expression_service.get_review_candidate = AsyncMock(
        return_value={"doc": candidate, "direction": direction} if candidate else None)
    expression_service.update_expression_sent = AsyncMock()
    expression_service.grade_expression = AsyncMock()

    user_service = MagicMock()
    user_service.get_user = AsyncMock(return_value=user)
    user_service.advance_onboarding = AsyncMock()

    llm_service = MagicMock()
    llm_service.generate_expression_card = AsyncMock(return_value=CARD)

    consumption_service = MagicMock()
    consumption_service.increment = AsyncMock()
    quota = make_quota(consumption_service, None if can_generate else QuotaExceeded(tier="normal", limit=10))

    sent = SimpleNamespace(message_id=sent_message_id)
    return SimpleNamespace(expression_service=expression_service, user_service=user_service,
                           llm_service=llm_service, consumption_service=consumption_service, quota=quota,
                           review_state=AsyncMock(), user=user, sent=sent)


def _use_cases(d) -> ReviewUseCases:
    return ReviewUseCases(review_state=d.review_state, expression_service=d.expression_service, user_service=d.user_service,
                          quota=d.quota, llm_service=d.llm_service,
                          user_defaults=TEST_LANGUAGE.user_defaults)


@pytest.fixture
def ui():
    """Formatting is presentation; pin that it is called with the right inputs."""
    with patch.object(review, "format_review_message", return_value="TEXT") as fmt_get, \
         patch.object(review, "get_review_keyboard", return_value="KB") as kb_get, \
         patch.object(scheduler, "format_review_message", return_value="TEXT") as fmt_sched, \
         patch.object(scheduler, "get_review_keyboard", return_value="KB") as kb_sched:
        yield SimpleNamespace(fmt_get=fmt_get, kb_get=kb_get, fmt_sched=fmt_sched, kb_sched=kb_sched)


def _message(sent):
    message = MagicMock()
    message.from_user.id = USER_ID
    message.answer = AsyncMock(return_value=sent)
    return message


async def _run_get(d):
    message = _message(d.sent)
    await review.cmd_get(message, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)
    return message


async def _run_scheduled(d):
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=d.sent)
    result = await scheduler.send_scheduled_review(bot=bot, user=d.user, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)
    return bot, result


CARD = ExpressionCard(success=True, norm="andare", learning_definition="muoversi",
                      translations=[TranslationLine(label="🇬🇧 EN", text="to go")],
                      learning_example="Vado a casa.", note=None, suggestions=[])
UNCLEAR_CARD = ExpressionCard(success=False, norm="andare", learning_definition=None, translations=[],
                              learning_example=None, note="Not clear", suggestions=[])

# Stored with the default test user's settings (see _user).
STORED = StoredCard(card=CARD, settings=CardSettings(level="B1", primary_language="en", secondary_language="fa"),
                    generated_at="2026-10-01T10:00:00Z")
WITH_STORED = {**CANDIDATE, "last_card": STORED.model_dump(mode="json")}


EXPECTED_LLM_CALL = call(raw="andare", level="B1", lang1_code="en", lang2_code="fa",
                         lang1_label="🇬🇧", lang2_label="🇮🇷")


# ===================================================================
# /get
# ===================================================================
class TestGetCommand:

    async def test_no_candidate_answers_no_memory(self, ui):
        d = _deps(candidate=None)
        message = await _run_get(d)

        message.answer.assert_awaited_once_with(i18n.get("commands.get.no_memory"))
        d.llm_service.generate_expression_card.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_quota_exceeded_answers_limit_and_generates_nothing(self, ui):
        d = _deps(can_generate=False)
        message = await _run_get(d)

        message.answer.assert_awaited_once_with(i18n.get(
            "messages.errors.quota_exceeded", type="card", tier="normal", limit=10))
        d.quota.check.assert_called_once_with(d.user, "cards")
        d.llm_service.generate_expression_card.assert_not_awaited()
        d.expression_service.update_expression_sent.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_sends_card_and_records_delivery(self, ui):
        d = _deps()
        message = await _run_get(d)

        assert d.llm_service.generate_expression_card.await_args == EXPECTED_LLM_CALL
        ui.fmt_get.assert_called_once_with(
            CARD, "andare", direction="forward", learning_flag=TEST_LANGUAGE.flag, label=None)
        ui.kb_get.assert_called_once_with(i18n, EXPRESSION_ID, direction="forward")
        message.answer.assert_awaited_once_with("TEXT", reply_markup="KB")
        d.expression_service.update_expression_sent.assert_awaited_once_with(EXPRESSION_ID, 42, last_card=ANY)
        d.review_state.mark_pending.assert_awaited_once_with(USER_ID)
        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=False)

    async def test_reverse_direction_reaches_format_and_keyboard(self, ui):
        d = _deps(direction="reverse")
        await _run_get(d)

        ui.fmt_get.assert_called_once_with(
            CARD, "andare", direction="reverse", learning_flag=TEST_LANGUAGE.flag, label=None)
        ui.kb_get.assert_called_once_with(i18n, EXPRESSION_ID, direction="reverse")

    async def test_own_api_key_is_passed_to_quota_and_consumption(self, ui):
        d = _deps(user=_user(api_config=UserAPIConfig(api_key="test")))
        await _run_get(d)

        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=True)

    async def test_send_failure_propagates_and_records_nothing(self, ui):
        d = _deps()
        message = _message(d.sent)
        message.answer = AsyncMock(side_effect=RuntimeError("telegram down"))

        with pytest.raises(RuntimeError):
            await review.cmd_get(message, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

        d.expression_service.update_expression_sent.assert_not_awaited()
        d.review_state.mark_pending.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_generation_failure_propagates_and_sends_nothing(self, ui):
        d = _deps()
        d.llm_service.generate_expression_card.side_effect = RuntimeError("all providers down")
        message = _message(d.sent)

        with pytest.raises(RuntimeError):
            await review.cmd_get(message, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

        message.answer.assert_not_awaited()
        d.expression_service.update_expression_sent.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_unsuccessful_card_without_stored_card_raises_and_sends_nothing(self, ui):
        d = _deps()
        d.llm_service.generate_expression_card.return_value = UNCLEAR_CARD
        message = _message(d.sent)

        with pytest.raises(CardGenerationFailed):
            await review.cmd_get(message, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

        message.answer.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    @pytest.mark.parametrize("failure", ["provider_error", "unclear_card"])
    async def test_failed_generation_sends_the_stored_card_free(self, ui, failure):
        d = _deps(candidate=WITH_STORED)
        if failure == "provider_error":
            d.llm_service.generate_expression_card.side_effect = RuntimeError("all providers down")
        else:
            d.llm_service.generate_expression_card.return_value = UNCLEAR_CARD
        message = await _run_get(d)

        ui.fmt_get.assert_called_once_with(CARD, "andare", direction="forward",
                                           learning_flag=TEST_LANGUAGE.flag, label=i18n.get("messages.saved_card"))
        message.answer.assert_awaited_once_with("TEXT", reply_markup="KB")
        d.expression_service.update_expression_sent.assert_awaited_once_with(EXPRESSION_ID, 42, last_card=None)
        d.review_state.mark_pending.assert_awaited_once_with(USER_ID)
        d.consumption_service.increment.assert_not_awaited()

    async def test_stored_card_with_older_settings_says_so(self, ui):
        d = _deps(candidate=WITH_STORED, user=_user(target_level="C1"))
        d.llm_service.generate_expression_card.side_effect = RuntimeError("all providers down")
        await _run_get(d)

        assert ui.fmt_get.call_args.kwargs["label"] == i18n.get("messages.saved_card_older_settings")

    async def test_fresh_card_is_stored_with_its_settings(self, ui):
        d = _deps()
        await _run_get(d)

        stored = d.expression_service.update_expression_sent.await_args.kwargs["last_card"]
        assert stored.card == CARD
        assert stored.settings == CardSettings(level="B1", primary_language="en", secondary_language="fa")

    async def test_missing_target_level_falls_back_to_default(self, ui):
        d = _deps(user=_user().model_copy(update={"target_level": None}))
        await _run_get(d)

        assert d.llm_service.generate_expression_card.await_args.kwargs["level"] == TEST_LANGUAGE.user_defaults.target_level


# ===================================================================
# Scheduled review
# ===================================================================
class TestScheduledReview:

    async def test_no_candidate_returns_false_silently(self, ui):
        d = _deps(candidate=None)
        bot, result = await _run_scheduled(d)

        assert result is False
        bot.send_message.assert_not_awaited()
        d.llm_service.generate_expression_card.assert_not_awaited()

    async def test_quota_exceeded_skips_without_message(self, ui):
        d = _deps(can_generate=False)
        bot, result = await _run_scheduled(d)

        assert result is False
        bot.send_message.assert_not_awaited()
        d.llm_service.generate_expression_card.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_uses_passed_user_without_refetching(self, ui):
        d = _deps()
        await _run_scheduled(d)

        d.user_service.get_user.assert_not_awaited()
        d.quota.check.assert_called_once_with(d.user, "cards")

    async def test_sends_card_and_records_delivery(self, ui):
        d = _deps(direction="reverse")
        bot, result = await _run_scheduled(d)

        assert result is True
        assert d.llm_service.generate_expression_card.await_args == EXPECTED_LLM_CALL
        ui.fmt_sched.assert_called_once_with(
            CARD, "andare", direction="reverse", learning_flag=TEST_LANGUAGE.flag, label=None)
        ui.kb_sched.assert_called_once_with(i18n, EXPRESSION_ID, direction="reverse")
        bot.send_message.assert_awaited_once_with(chat_id=USER_ID, text="TEXT", reply_markup="KB")
        d.expression_service.update_expression_sent.assert_awaited_once_with(EXPRESSION_ID, 42, last_card=ANY)
        d.review_state.mark_pending.assert_awaited_once_with(USER_ID)
        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=False)

    async def test_send_failure_propagates_and_records_nothing(self, ui):
        d = _deps()
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))

        with pytest.raises(RuntimeError):
            await scheduler.send_scheduled_review(bot=bot, user=d.user, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

        d.expression_service.update_expression_sent.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_generation_failure_propagates_and_sends_nothing(self, ui):
        d = _deps()
        d.llm_service.generate_expression_card.side_effect = RuntimeError("all providers down")
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=d.sent)

        with pytest.raises(RuntimeError):
            await scheduler.send_scheduled_review(bot=bot, user=d.user, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

        bot.send_message.assert_not_awaited()
        d.expression_service.update_expression_sent.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_unsuccessful_card_without_stored_card_raises_and_sends_nothing(self, ui):
        d = _deps()
        d.llm_service.generate_expression_card.return_value = UNCLEAR_CARD
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=d.sent)

        with pytest.raises(CardGenerationFailed):
            await scheduler.send_scheduled_review(bot=bot, user=d.user, review_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

        bot.send_message.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_provider_failure_sends_the_stored_card_free(self, ui):
        d = _deps(candidate=WITH_STORED)
        d.llm_service.generate_expression_card.side_effect = RuntimeError("all providers down")
        bot, result = await _run_scheduled(d)

        assert result is True
        ui.fmt_sched.assert_called_once_with(CARD, "andare", direction="forward",
                                             learning_flag=TEST_LANGUAGE.flag, label=i18n.get("messages.saved_card"))
        d.expression_service.update_expression_sent.assert_awaited_once_with(EXPRESSION_ID, 42, last_card=None)
        d.consumption_service.increment.assert_not_awaited()


# ===================================================================
# Grading
# ===================================================================
def _callback(text="CARD TEXT"):
    callback = MagicMock()
    callback.from_user.id = USER_ID
    callback.data = "grade:x:4:fwd"
    callback.message.text = text
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def _run_grade(d, *, grade=4, direction="fwd", logger_bot=None):
    callback = _callback()
    data = GradeCallback(expression_id=EXPRESSION_ID, grade=grade, direction=direction)
    await review.handle_grade(callback, data, review_use_cases=_use_cases(d),
                              logger_bot=logger_bot or MagicMock(), admin_id=1, i18n=i18n)
    return callback


class TestGrade:

    @pytest.mark.parametrize("code, direction", [("fwd", "forward"), ("rev", "reverse")])
    async def test_success_records_grade_and_edits_message(self, code, direction):
        d = _deps(user=_user(onboarding_step=2))
        d.expression_service.grade_expression.return_value = {"value": "andare"}
        callback = await _run_grade(d, grade=4, direction=code)

        d.expression_service.grade_expression.assert_awaited_once_with(USER_ID, EXPRESSION_ID, 4, direction)
        callback.message.edit_text.assert_awaited_once_with(
            "CARD TEXT" + i18n.get("callbacks.grade.rated", grade=4))
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.grade.success"), show_alert=False)
        callback.message.answer.assert_not_awaited()
        d.user_service.advance_onboarding.assert_not_awaited()

    async def test_first_review_shows_tip_and_advances_onboarding(self):
        d = _deps(user=_user(onboarding_step=1))
        d.expression_service.grade_expression.return_value = {"value": "andare"}
        callback = await _run_grade(d)

        callback.message.answer.assert_awaited_once_with(i18n.get("messages.tips.first_review"))
        d.user_service.advance_onboarding.assert_awaited_once_with(USER_ID, 1)

    async def test_missing_expression_alerts_and_edits_nothing(self):
        d = _deps()
        d.expression_service.grade_expression.return_value = None
        callback = await _run_grade(d)

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.grade.error_missing"), show_alert=True)
        callback.message.edit_text.assert_not_awaited()

    async def test_out_of_range_grade_alerts_invalid_data_and_admin(self):
        d = _deps()
        # The real ExpressionService rejects it; the handler must turn that into the invalid-data alert.
        d.expression_service.grade_expression.side_effect = ValueError("grade must be an integer 0-5, got 9")
        logger_bot = MagicMock()
        with patch.object(review, "notify_admin_with_trace", new=AsyncMock()) as notify:
            callback = await _run_grade(d, grade=9, logger_bot=logger_bot)

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.grade.invalid_data"), show_alert=True)
        callback.message.edit_text.assert_not_awaited()
        notify.assert_awaited_once()
        assert notify.await_args.args[0] is logger_bot

    async def test_unexpected_error_alerts_user_and_admin(self):
        d = _deps()
        d.expression_service.grade_expression.side_effect = RuntimeError("db down")
        logger_bot = MagicMock()
        with patch.object(review, "notify_admin_with_trace", new=AsyncMock()) as notify:
            callback = await _run_grade(d, logger_bot=logger_bot)

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.grade.error_generic"), show_alert=True)
        notify.assert_awaited_once()
        assert notify.await_args.args[0] is logger_bot
