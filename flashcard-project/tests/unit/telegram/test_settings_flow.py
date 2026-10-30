"""
Tests for /settings at the Telegram entry point: menu, navigation, selections,
language prompts, and the pause/resume/close reply buttons.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import ForceReply, ReplyKeyboardRemove

from flashcard.app.settings import SettingsUseCases
from flashcard.services.user import UserService
from tests.integration.helpers import make_cols
from flashcard.schemas.languages import get_language_flag, get_language_name
from flashcard.schemas.user import UserDB
from tests.helpers import TEST_I18N as i18n
from flashcard.telegram.handlers import reply_commands, user_settings
from flashcard.telegram.keyboards import (
    get_interval_settings_keyboard, get_language_settings_keyboard, get_level_selection_keyboard,
    get_main_settings_keyboard, get_reply_settings_keyboard,
)
from flashcard.telegram.states.settings import SettingsPrompts
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback
from tests.helpers import make_user, TEST_LANGUAGE


USER_ID = 777


def _user(**overrides) -> UserDB:
    fields = {"user_id": USER_ID}
    fields.update(overrides)
    return make_user(**fields)


def _deps(user=None, *, state_name=None):
    # A real UserService on the in-memory Mongo fake, so its setters' rules apply.
    doc = (user or _user()).model_dump()
    cols = make_cols(users=[doc])
    user_service = UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults)

    state = MagicMock()
    state.get_state = AsyncMock(return_value=state_name)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return SimpleNamespace(user_service=user_service, state=state, initial=dict(doc),
                           saved=lambda: cols["users"].docs[0],
                           settings_use_cases=SettingsUseCases(user_service=user_service))


def _message(text="/settings"):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    message.answer = AsyncMock()
    message.reply = AsyncMock()
    return message


def _callback():
    callback = MagicMock()
    callback.from_user.id = USER_ID
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    return callback


async def _nav(d, section):
    callback = _callback()
    await user_settings.handle_settings_nav(
        callback, SettingsCallback(action="nav", section=section), settings_use_cases=d.settings_use_cases,
        state=d.state, i18n=i18n)
    return callback


async def _select(d, section, value=None):
    callback = _callback()
    await user_settings.handle_settings_select(
        callback, SettingsCallback(action="select", section=section, value=value),
        settings_use_cases=d.settings_use_cases, i18n=i18n)
    return callback


async def _answer_prompt(d, text):
    message = _message(text)
    await user_settings.answer_setting_prompt(message, state=d.state, settings_use_cases=d.settings_use_cases, i18n=i18n)
    return message


def _menu_text(user):
    return user_settings._get_settings_menu_text(i18n, user)


class TestSettingsMenu:

    async def test_settings_shows_menu_and_reply_controls(self):
        user = _user(target_level="B1", review_interval_minutes=60)
        d = _deps(user)
        message = _message()
        await user_settings.cmd_settings(message, settings_use_cases=d.settings_use_cases, i18n=i18n)

        first, second = message.answer.await_args_list
        assert first.args == (_menu_text(user),)
        assert first.kwargs == {"reply_markup": get_main_settings_keyboard(i18n, user)}
        assert second.args == (i18n.get("commands.settings.controls"),)
        assert second.kwargs == {"reply_markup": get_reply_settings_keyboard(i18n, True)}

    async def test_paused_user_gets_resume_button(self):
        d = _deps(_user(is_active=False))
        message = _message()
        await user_settings.cmd_settings(message, settings_use_cases=d.settings_use_cases, i18n=i18n)

        assert message.answer.await_args_list[1].kwargs == {"reply_markup": get_reply_settings_keyboard(i18n, False)}

    async def test_menu_text_lists_current_settings(self):
        text = _menu_text(_user(primary_language="fa", secondary_language="de", target_level="C1",
                                review_interval_minutes=90, review_mode="dual"))

        assert i18n.get("commands.settings.menu.heading") in text
        assert "🇮🇷" in text and "🇩🇪" in text
        assert "C1" in text and "90" in text

    @pytest.mark.parametrize("secondary", [None, "none"])
    async def test_menu_text_without_secondary_language(self, secondary):
        text = _menu_text(_user(secondary_language=secondary))

        assert i18n.get("commands.settings.menu.secondary_lang",
                        secondary_lang=i18n.get("commands.settings.no_language")) in text

    @pytest.mark.parametrize("mode", ["standard", "dual"])
    async def test_review_mode_line_and_button_are_translated(self, mode):
        label = i18n.get(f"commands.settings.mode_{mode}")

        assert _menu_text(_user(review_mode=mode)).endswith(
            i18n.get("commands.settings.menu.review_mode", review_mode=label))
        assert i18n.get("commands.settings.menu_options.review_mode", mode=label) in [
            b.text for row in get_main_settings_keyboard(i18n, _user(review_mode=mode)).inline_keyboard for b in row]


class TestSettingsNavigation:

    async def test_main_redraws_menu(self):
        user = _user()
        d = _deps(user)
        callback = await _nav(d, "main")

        callback.message.edit_text.assert_awaited_once_with(
            text=_menu_text(user), reply_markup=get_main_settings_keyboard(i18n, user))
        callback.answer.assert_awaited_once()

    async def test_language_menu(self):
        user = _user()
        d = _deps(user)
        callback = await _nav(d, "lang_menu")

        callback.message.edit_text.assert_awaited_once_with(
            text=i18n.get("commands.settings.sections.language"), reply_markup=get_language_settings_keyboard(i18n, user))

    async def test_level_menu_marks_current_level(self):
        d = _deps(_user(target_level="B2"))
        callback = await _nav(d, "set_level")

        callback.message.edit_text.assert_awaited_once_with(
            text=i18n.get("commands.settings.prompts.level_select"), reply_markup=get_level_selection_keyboard(i18n, "B2"))

    async def test_interval_menu_marks_current_interval(self):
        d = _deps(_user(review_interval_minutes=90))
        callback = await _nav(d, "interval")

        callback.message.edit_text.assert_awaited_once_with(
            text=i18n.get("commands.settings.sections.interval"), reply_markup=get_interval_settings_keyboard(i18n, 90),
            parse_mode="Markdown")

    @pytest.mark.parametrize("section, prompt, key", [
        ("set_lang_p", SettingsPrompts.waiting_primary_lang, "commands.settings.prompts.primary_lang"),
        ("set_lang_s", SettingsPrompts.waiting_secondary_lang, "commands.settings.prompts.secondary_lang"),
    ])
    async def test_language_buttons_ask_with_force_reply(self, section, prompt, key):
        d = _deps()
        callback = await _nav(d, section)

        d.state.set_state.assert_awaited_once_with(prompt)
        call = callback.message.answer.await_args
        assert call.args == (i18n.get(key),)
        assert isinstance(call.kwargs["reply_markup"], ForceReply)
        assert d.saved() == d.initial  # nothing written

    async def test_api_shows_pending_feature_alert(self):
        d = _deps()
        callback = await _nav(d, "api")

        assert callback.answer.await_args_list[0].args == (i18n.get("commands.settings.sections.api"),)
        assert callback.answer.await_args_list[0].kwargs == {"show_alert": True}

    @pytest.mark.parametrize("section", ["main", "lang_menu", "set_lang_p", "set_lang_s", "set_level", "interval",
                                         "api"])
    async def test_every_section_answers_the_callback_once(self, section):
        callback = await _nav(_deps(), section)

        assert callback.answer.await_count == 1


class TestSettingsSelect:

    async def test_level_is_saved_and_marked(self):
        d = _deps()
        callback = await _select(d, "target_level", "C1")

        assert d.saved()["target_level"] == "C1"
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=get_level_selection_keyboard(i18n, "C1"))
        callback.answer.assert_awaited_once_with(i18n.get("commands.settings.saved"), show_alert=False)

    async def test_interval_is_saved_as_int_and_marked(self):
        d = _deps()
        callback = await _select(d, "interval", "120")

        assert d.saved()["review_interval_minutes"] == 120
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=get_interval_settings_keyboard(i18n, 120))
        callback.answer.assert_awaited_once_with(i18n.get("commands.settings.saved"), show_alert=False)

    @pytest.mark.parametrize("current, new", [("standard", "dual"), ("dual", "standard")])
    async def test_review_mode_button_switches_to_the_named_mode(self, current, new):
        d = _deps(_user(review_mode=current))
        callback = await _select(d, "review_mode", new)

        assert d.saved()["review_mode"] == new
        updated = _user(review_mode=new)
        callback.message.edit_text.assert_awaited_once_with(
            text=_menu_text(updated), reply_markup=get_main_settings_keyboard(i18n, updated))
        callback.answer.assert_awaited_once_with(i18n.get(
            "commands.settings.switched_mode", mode=i18n.get(f"commands.settings.mode_{new}")), show_alert=False)

    async def test_stale_review_mode_button_changes_nothing(self):
        """A double tap or an old menu names the mode already set; it is not flipped back."""
        d = _deps(_user(review_mode="dual"))
        await _select(d, "review_mode", "dual")

        assert d.saved()["review_mode"] == "dual"

    @pytest.mark.parametrize("current, new", [("standard", "dual"), ("dual", "standard")])
    async def test_legacy_toggle_button_still_flips(self, current, new):
        """Menus sent before buttons named their target mode carry value "toggle"."""
        d = _deps(_user(review_mode=current))
        await _select(d, "review_mode", "toggle")

        assert d.saved()["review_mode"] == new

    @pytest.mark.parametrize("current", ["standard", "dual"])
    def test_review_mode_button_names_the_other_mode(self, current):
        markup = get_main_settings_keyboard(i18n, _user(review_mode=current))
        data = [b.callback_data for row in markup.inline_keyboard for b in row if "review_mode" in b.callback_data]

        other = "dual" if current == "standard" else "standard"
        assert data == [SettingsCallback(action="select", section="review_mode", value=other).pack()]

    @pytest.mark.parametrize("minutes", ["15", "45", "240"])
    async def test_any_interval_in_range_is_saved(self, minutes):
        d = _deps()
        callback = await _select(d, "interval", minutes)

        assert d.saved()["review_interval_minutes"] == int(minutes)
        callback.answer.assert_awaited_once_with(i18n.get("commands.settings.saved"), show_alert=False)

    @pytest.mark.parametrize("section, value", [
        # Callback data can be forged by a client; a bad level would fail UserDB validation
        # on every later get_user and lock the user out.
        ("target_level", "Z9"),
        ("target_level", None),
        ("interval", "-5"),
        ("interval", "14"),
        ("interval", "241"),
        ("interval", "soon"),
        ("interval", None),
        ("nickname", "bob"),
    ])
    async def test_invalid_values_are_rejected_without_saving(self, section, value):
        d = _deps()
        callback = await _select(d, section, value)

        assert d.saved() == d.initial  # nothing written
        callback.message.edit_reply_markup.assert_not_awaited()
        callback.answer.assert_awaited_once_with(i18n.get("commands.settings.invalid_value"), show_alert=True)


class TestLanguagePrompt:

    @pytest.mark.parametrize("prompt, text, field, code", [
        (SettingsPrompts.waiting_primary_lang, "Farsi", "primary_language", "fa"),
        (SettingsPrompts.waiting_primary_lang, " DE ", "primary_language", "de"),
        (SettingsPrompts.waiting_secondary_lang, "english", "secondary_language", "en"),
    ])
    async def test_valid_language_is_saved_confirmed_and_menu_shown(self, prompt, text, field, code):
        user = _user()
        d = _deps(user, state_name=prompt.state)
        message = await _answer_prompt(d, text)

        assert d.saved()[field] == code
        label = "primary_label" if field == "primary_language" else "secondary_label"
        message.reply.assert_awaited_once_with(i18n.get(
            "commands.settings.prompts.success_lang", type=i18n.get(f"commands.settings.prompts.{label}"),
            lang=get_language_name(code), flag=get_language_flag(code)))
        d.state.clear.assert_awaited_once()
        # The menu shows the language just chosen.
        message.answer.assert_awaited_once_with(
            i18n.get("commands.settings.sections.language"),
            reply_markup=get_language_settings_keyboard(i18n, user.model_copy(update={field: code})))

    async def test_secondary_none_is_confirmed_with_localized_none(self):
        d = _deps(state_name=SettingsPrompts.waiting_secondary_lang.state)
        message = await _answer_prompt(d, "none")

        assert d.saved()["secondary_language"] == "none"
        message.reply.assert_awaited_once_with(i18n.get(
            "commands.settings.prompts.success_lang", type=i18n.get("commands.settings.prompts.secondary_label"),
            lang=i18n.get("commands.settings.no_language"), flag="⚪"))

    @pytest.mark.parametrize("prompt, text", [
        (SettingsPrompts.waiting_primary_lang, "klingon"),
        (SettingsPrompts.waiting_primary_lang, "none"),
        (SettingsPrompts.waiting_secondary_lang, "klingon"),
        # A sticker or photo has no text; saving None would break the user record.
        (SettingsPrompts.waiting_primary_lang, None),
        (SettingsPrompts.waiting_secondary_lang, None),
    ])
    async def test_invalid_language_is_rejected_and_prompt_ends(self, prompt, text):
        user = _user()
        d = _deps(user, state_name=prompt.state)
        message = await _answer_prompt(d, text)

        assert d.saved() == d.initial  # nothing written
        message.reply.assert_awaited_once_with(
            i18n.get("commands.settings.prompts.invalid_lang"), reply_markup=get_language_settings_keyboard(i18n, user))
        d.state.clear.assert_awaited_once()


class TestReplyButtons:

    @pytest.mark.parametrize("was_active, button, key", [
        (True, "messages.buttons.pause_learning", "messages.notifications.paused"),
        (False, "messages.buttons.resume_learning", "messages.notifications.resumed"),
    ])
    async def test_pause_resume_toggles_and_swaps_button(self, was_active, button, key):
        d = _deps(_user(is_active=was_active))
        message = _message(i18n.get(button))
        await reply_commands.handle_status_change(message, settings_use_cases=d.settings_use_cases, i18n=i18n)

        assert d.saved()["is_active"] is not was_active
        message.answer.assert_awaited_once_with(
            i18n.get(key), reply_markup=get_reply_settings_keyboard(i18n, not was_active))

    @pytest.mark.parametrize("active, button", [
        (False, "messages.buttons.pause_learning"),
        (True, "messages.buttons.resume_learning"),
    ])
    async def test_repeated_tap_changes_nothing(self, active, button):
        """Pause when already paused (double tap, stale keyboard) stays paused."""
        d = _deps(_user(is_active=active))
        await reply_commands.handle_status_change(_message(i18n.get(button)), settings_use_cases=d.settings_use_cases, i18n=i18n)

        assert d.saved()["is_active"] is active

    async def test_close_removes_the_reply_keyboard(self):
        message = _message(i18n.get("messages.buttons.close_settings"))
        await reply_commands.handle_close_settings(message, i18n=i18n)

        call = message.answer.await_args
        assert call.args == (i18n.get("commands.settings.closed"),)
        assert isinstance(call.kwargs["reply_markup"], ReplyKeyboardRemove)
