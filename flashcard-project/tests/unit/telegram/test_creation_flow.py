"""
Characterization tests for the creation flow: text message -> card, regenerate, save.

They pin current behavior at the entry points so creation logic can be moved
into a use-case layer without changing what users see or what is written.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from flashcard.app.creation import CreationUseCases
from flashcard.schemas.expression import ExpressionCard, TranslationLine
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier
from tests.helpers import TEST_I18N as i18n
from flashcard.services.language_validation import LanguageValidationResult
from flashcard.telegram.handlers import creation
from flashcard.telegram.keyboards import expression_action_kb
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.app.quota import QuotaExceeded
from tests.helpers import TEST_LANGUAGE, make_quota, make_user


USER_ID = 222


def _card(success=True, norm="andare") -> ExpressionCard:
    if success:
        return ExpressionCard(success=True, norm=norm, learning_definition="muoversi",
                              translations=[TranslationLine(label="🇬🇧 EN", text="to go")],
                              learning_example="Vado a casa.", note=None, suggestions=[])
    return ExpressionCard(success=False, norm=norm, learning_definition=None, translations=[],
                          learning_example=None, note="Not clear", suggestions=["andare"])


def _user(**overrides) -> UserDB:
    fields = {"user_id": USER_ID, "primary_language": "en", "secondary_language": None,
              "target_level": "B1", "tier": UserTier.normal}
    fields.update(overrides)
    return make_user(**fields)


def _deps(*, card=None, user=None, can_generate=True, validation=None):
    user = user or _user()
    llm_service = MagicMock()
    llm_service.generate_expression_card = AsyncMock(return_value=card or _card())

    user_service = MagicMock()
    user_service.get_user = AsyncMock(return_value=user)
    user_service.advance_onboarding = AsyncMock()

    consumption_service = MagicMock()
    consumption_service.increment = AsyncMock()
    quota = make_quota(consumption_service, None if can_generate else QuotaExceeded(tier="normal", limit=10))

    expression_service = MagicMock()
    expression_service.add_expression = AsyncMock(return_value=True)

    validator = None
    if validation is not None:
        validator = MagicMock()
        validator.validate_expression = AsyncMock(return_value=validation)

    return SimpleNamespace(llm_service=llm_service, user_service=user_service,
                           consumption_service=consumption_service, quota=quota,
                           expression_service=expression_service, validator=validator, user=user)


def _use_cases(d) -> CreationUseCases:
    return CreationUseCases(review_state=AsyncMock(), expression_service=d.expression_service, user_service=d.user_service,
                            quota=d.quota, llm_service=d.llm_service,
                            language_validator=d.validator)


QUOTA_TEXT = lambda: i18n.get("messages.errors.quota_exceeded", type="card", tier="normal", limit=10)


# ===================================================================
# Text message -> card
# ===================================================================
async def _run_text(d, text="andare"):
    status = MagicMock()
    status.edit_text = AsyncMock()
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    message.answer = AsyncMock(return_value=status)
    await creation.handle_text_message(message, creation_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)
    return message, status


class TestTextMessage:

    async def test_success_shows_card_with_actions_and_counts_usage(self):
        d = _deps()
        message, status = await _run_text(d)

        message.answer.assert_awaited_once_with(i18n.get("messages.working"))
        status.edit_text.assert_awaited_once_with(
            text=render_expression_card(_card(), learning_flag=TEST_LANGUAGE.flag)["content"], reply_markup=expression_action_kb(i18n, "andare"))
        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=False)

    async def test_generation_uses_user_preferences_without_defaults(self):
        d = _deps(user=_user(primary_language="fa", secondary_language="en", target_level="A2"))
        await _run_text(d)

        kwargs = d.llm_service.generate_expression_card.await_args.kwargs
        assert {k: kwargs[k] for k in ("raw", "level", "lang1_code", "lang2_code", "lang1_label", "lang2_label")} == {
            "raw": "andare", "level": "A2", "lang1_code": "fa", "lang2_code": "en",
            "lang1_label": "🇮🇷", "lang2_label": "🇬🇧"}

    async def test_no_secondary_language_passes_no_label(self):
        d = _deps()
        await _run_text(d)

        kwargs = d.llm_service.generate_expression_card.await_args.kwargs
        assert kwargs["lang2_code"] is None
        assert kwargs["lang2_label"] is None

    async def test_provider_fallback_updates_status_message(self):
        d = _deps()
        _, status = await _run_text(d)

        await d.llm_service.generate_expression_card.await_args.kwargs["on_fallback"]()
        assert status.edit_text.await_args_list[-1].args == (i18n.get("messages.llm_fallback"),)

    async def test_own_api_key_is_used_for_quota_and_usage(self):
        d = _deps(user=_user(api_config=UserAPIConfig(api_key="test")))
        await _run_text(d)

        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=True)

    async def test_unclear_input_shows_note_without_actions_or_usage(self):
        d = _deps(card=_card(success=False))
        _, status = await _run_text(d)

        status.edit_text.assert_awaited_once_with(text="Not clear", reply_markup=None)
        d.consumption_service.increment.assert_not_awaited()

    async def test_quota_exceeded_shows_limit_and_generates_nothing(self):
        d = _deps(can_generate=False)
        _, status = await _run_text(d)

        status.edit_text.assert_awaited_once_with(text=QUOTA_TEXT(), reply_markup=None)
        d.llm_service.generate_expression_card.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_invalid_language_shows_up_to_three_suggestions(self):
        d = _deps(validation=LanguageValidationResult(is_valid=False, suggestions=["a", "b", "c", "d"]))
        _, status = await _run_text(d)

        expected = i18n.get("messages.errors.invalid_learning_language_input") + "\na\nb\nc"
        status.edit_text.assert_awaited_once_with(text=expected, reply_markup=None)
        d.quota.check.assert_not_called()
        d.llm_service.generate_expression_card.assert_not_awaited()

    async def test_validator_normalized_text_is_generated(self):
        d = _deps(validation=LanguageValidationResult(is_valid=True, normalized_text="andare"))
        await _run_text(d, text="  Andare ")

        assert d.llm_service.generate_expression_card.await_args.kwargs["raw"] == "andare"

    async def test_without_validator_raw_text_is_generated(self):
        d = _deps()
        await _run_text(d, text="Andare")

        assert d.llm_service.generate_expression_card.await_args.kwargs["raw"] == "Andare"

    async def test_generation_failure_propagates_without_usage(self):
        d = _deps()
        d.llm_service.generate_expression_card.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError):
            await _run_text(d)
        d.consumption_service.increment.assert_not_awaited()


# ===================================================================
# Regenerate
# ===================================================================
def _callback(data, markup=None, text="CARD TEXT"):
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = USER_ID
    callback.message.text = text
    callback.message.html_text = text
    callback.message.caption = None
    callback.message.reply_markup = markup
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def _run_regen(d, data="regen:andare"):
    callback = _callback(data, markup=expression_action_kb(i18n, "andare"))
    await creation.handle_regen(callback, creation_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)
    return callback


class TestRegenerate:

    async def test_success_replaces_card_and_keeps_actions(self):
        d = _deps()
        callback = await _run_regen(d)

        assert callback.message.edit_text.await_args_list[0].args == (i18n.get("callbacks.regen.working"),)
        assert callback.message.edit_text.await_args_list[-1].kwargs == {
            "text": render_expression_card(_card(), learning_flag=TEST_LANGUAGE.flag)["content"], "reply_markup": expression_action_kb(i18n, "andare")}
        assert d.llm_service.generate_expression_card.await_args.kwargs["raw"] == "andare"
        d.consumption_service.increment.assert_awaited_once_with(
            USER_ID, "cards_generated", uses_own_key=False)

    async def test_quota_exceeded_keeps_the_card_and_sends_the_limit(self):
        """The quota text is too long for an alert, so it is a message; the card stays usable."""
        d = _deps(can_generate=False)
        callback = await _run_regen(d)

        assert callback.message.edit_text.await_args_list[-1].kwargs == {
            "text": "CARD TEXT", "reply_markup": expression_action_kb(i18n, "andare")}
        callback.message.answer.assert_awaited_once_with(QUOTA_TEXT())
        d.consumption_service.increment.assert_not_awaited()

    async def test_unclear_result_keeps_the_card_and_alerts(self):
        d = _deps(card=_card().model_copy(update={"success": False}))
        callback = await _run_regen(d)

        assert callback.message.edit_text.await_args_list[-1].kwargs == {
            "text": "CARD TEXT", "reply_markup": expression_action_kb(i18n, "andare")}
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.regen.failed"), show_alert=True)
        callback.message.answer.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_provider_error_restores_the_card_and_propagates(self):
        """The error handler tells the user; the card must not stay stuck on "working"."""
        d = _deps()
        d.llm_service.generate_expression_card.side_effect = RuntimeError("provider down")

        callback = _callback("regen:andare", markup=expression_action_kb(i18n, "andare"))

        with pytest.raises(RuntimeError, match="provider down"):
            await creation.handle_regen(callback, creation_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)
        assert callback.message.edit_text.await_args_list[-1].kwargs == {
            "text": "CARD TEXT", "reply_markup": expression_action_kb(i18n, "andare")}

    async def test_failed_restore_does_not_hide_the_provider_error(self):
        d = _deps()
        d.llm_service.generate_expression_card.side_effect = RuntimeError("provider down")
        callback = _callback("regen:andare", markup=expression_action_kb(i18n, "andare"))
        callback.message.edit_text.side_effect = [None, RuntimeError("message gone")]

        with pytest.raises(RuntimeError, match="provider down"):
            await creation.handle_regen(callback, creation_use_cases=_use_cases(d), language=TEST_LANGUAGE, i18n=i18n)

    async def test_expression_with_colon_is_kept_whole(self):
        d = _deps()
        await _run_regen(d, data="regen:a:b")

        assert d.llm_service.generate_expression_card.await_args.kwargs["raw"] == "a:b"


# ===================================================================
# Save
# ===================================================================
async def _run_save(d, data="save:andare", markup=None):
    callback = _callback(data, markup=markup)
    await creation.handle_save(callback, creation_use_cases=_use_cases(d), i18n=i18n)
    return callback


class TestSave:

    async def test_saved_confirms_and_tags_message(self):
        d = _deps(user=_user(onboarding_step=2))
        callback = await _run_save(d)

        d.expression_service.add_expression.assert_awaited_once_with(USER_ID, "andare")
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.save.success_message"), show_alert=True)
        callback.message.edit_text.assert_awaited_once_with(
            "CARD TEXT" + i18n.get("callbacks.save.success_tag", norm="andare"))
        callback.message.answer.assert_not_awaited()
        d.user_service.advance_onboarding.assert_not_awaited()

    async def test_first_save_shows_tip_and_advances_onboarding(self):
        d = _deps(user=_user(onboarding_step=0))
        callback = await _run_save(d)

        callback.message.answer.assert_awaited_once_with(i18n.get("messages.tips.first_save"))
        d.user_service.advance_onboarding.assert_awaited_once_with(USER_ID, 0)

    async def test_duplicate_alerts_and_removes_only_save_button(self):
        d = _deps()
        d.expression_service.add_expression.return_value = False
        callback = await _run_save(d, markup=expression_action_kb(i18n, "andare"))

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.save.already_exists"), show_alert=True)
        markup = callback.message.edit_reply_markup.await_args.kwargs["reply_markup"]
        remaining = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert remaining == ["regen:andare"]
        callback.message.edit_text.assert_not_awaited()

    async def test_duplicate_without_save_button_keeps_keyboard(self):
        d = _deps()
        d.expression_service.add_expression.return_value = False
        only_regen = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="regen", callback_data="regen:andare")]])
        callback = await _run_save(d, markup=only_regen)

        markup = callback.message.edit_reply_markup.await_args.kwargs["reply_markup"]
        assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["regen:andare"]

    async def test_expression_with_colon_is_saved_whole(self):
        d = _deps()
        await _run_save(d, data="save:a:b")

        d.expression_service.add_expression.assert_awaited_once_with(USER_ID, "a:b")
