"""
Tests for /settings at the Telegram entry point: menu, navigation, selections,
language prompts, and the pause/resume/close reply buttons.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import ForceReply, ReplyKeyboardRemove

from flashcard.app.settings import SettingsUseCases
from flashcard.schemas.languages import get_language_flag, get_language_name
from flashcard.schemas.user import UserDB
from flashcard.services.i18n import i18n
from flashcard.telegram.handlers import reply_commands, user_settings
from flashcard.telegram.keyboards import (
    get_interval_settings_keyboard, get_language_settings_keyboard, get_level_selection_keyboard,
    get_main_settings_keyboard, get_reply_settings_keyboard,
)
from flashcard.telegram.states.settings import SettingsPrompts
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback


USER_ID = 777


def _user(**overrides) -> UserDB:
    fields = {"user_id": str(USER_ID)}
    fields.update(overrides)
    return UserDB(**fields)


def _deps(user=None, *, state_name=None):
    # Stored user: reads return a copy, writes update it.
    stored = {"user": user or _user()}

    async def update_setting(user_id, field, value):
        stored["user"] = stored["user"].model_copy(update={field: value})

    async def toggle_active_status(user_id):
        await update_setting(user_id, "is_active", not stored["user"].is_active)
        return stored["user"].is_active

    user_service = MagicMock()
    user_service.get_user = AsyncMock(side_effect=lambda user_id: stored["user"].model_copy())
    user_service.update_setting = AsyncMock(side_effect=update_setting)
    user_service.toggle_active_status = AsyncMock(side_effect=toggle_active_status)

    state = MagicMock()
    state.get_state = AsyncMock(return_value=state_name)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return SimpleNamespace(user_service=user_service, state=state, stored=stored,
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
        state=d.state)
    return callback


async def _select(d, section, value=None):
    callback = _callback()
    await user_settings.handle_settings_select(
        callback, SettingsCallback(action="select", section=section, value=value),
        settings_use_cases=d.settings_use_cases)
    return callback


async def _answer_prompt(d, text):
    message = _message(text)
    await user_settings.answer_setting_prompt(message, state=d.state, settings_use_cases=d.settings_use_cases)
    return message


def _menu_text(user):
    return user_settings._get_settings_menu_text(user)


class TestSettingsMenu:

    async def test_settings_shows_menu_and_reply_controls(self):
        user = _user(target_level="B1", review_interval_minutes=60)
        d = _deps(user)
        message = _message()
        await user_settings.cmd_settings(message, settings_use_cases=d.settings_use_cases)

        first, second = message.answer.await_args_list
        assert first.args == (_menu_text(user),)
        assert first.kwargs == {"reply_markup": get_main_settings_keyboard(user)}
        assert second.args == (i18n.get("commands.settings.controls"),)
        assert second.kwargs == {"reply_markup": get_reply_settings_keyboard(True)}

    async def test_paused_user_gets_resume_button(self):
        d = _deps(_user(is_active=False))
        message = _message()
        await user_settings.cmd_settings(message, settings_use_cases=d.settings_use_cases)

        assert message.answer.await_args_list[1].kwargs == {"reply_markup": get_reply_settings_keyboard(False)}

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
            b.text for row in get_main_settings_keyboard(_user(review_mode=mode)).inline_keyboard for b in row]


class TestSettingsNavigation:

    async def test_main_redraws_menu(self):
        user = _user()
        d = _deps(user)
        callback = await _nav(d, "main")

        callback.message.edit_text.assert_awaited_once_with(
            text=_menu_text(user), reply_markup=get_main_settings_keyboard(user))
        callback.answer.assert_awaited_once()

    async def test_language_menu(self):
        user = _user()
        d = _deps(user)
        callback = await _nav(d, "lang_menu")

        callback.message.edit_text.assert_awaited_once_with(
            text=i18n.get("commands.settings.sections.language"), reply_markup=get_language_settings_keyboard(user))

    async def test_level_menu_marks_current_level(self):
        d = _deps(_user(target_level="B2"))
        callback = await _nav(d, "set_level")

        callback.message.edit_text.assert_awaited_once_with(
            text=i18n.get("commands.settings.prompts.level_select"), reply_markup=get_level_selection_keyboard("B2"))

    async def test_interval_menu_marks_current_interval(self):
        d = _deps(_user(review_interval_minutes=90))
        callback = await _nav(d, "interval")

        callback.message.edit_text.assert_awaited_once_with(
            text=i18n.get("commands.settings.sections.interval"), reply_markup=get_interval_settings_keyboard(90),
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
        d.user_service.update_setting.assert_not_awaited()

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

        d.user_service.update_setting.assert_awaited_once_with(USER_ID, "target_level", "C1")
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=get_level_selection_keyboard("C1"))
        callback.answer.assert_awaited_once_with(i18n.get("commands.settings.saved"), show_alert=False)

    async def test_interval_is_saved_as_int_and_marked(self):
        d = _deps()
        callback = await _select(d, "interval", "120")

        d.user_service.update_setting.assert_awaited_once_with(USER_ID, "review_interval_minutes", 120)
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=get_interval_settings_keyboard(120))
        callback.answer.assert_awaited_once_with(i18n.get("commands.settings.saved"), show_alert=False)

    @pytest.mark.parametrize("current, new", [("standard", "dual"), ("dual", "standard")])
    async def test_review_mode_toggles_and_redraws_menu(self, current, new):
        d = _deps(_user(review_mode=current))
        callback = await _select(d, "review_mode", "toggle")

        d.user_service.update_setting.assert_awaited_once_with(USER_ID, "review_mode", new)
        updated = _user(review_mode=new)
        callback.message.edit_text.assert_awaited_once_with(
            text=_menu_text(updated), reply_markup=get_main_settings_keyboard(updated))
        callback.answer.assert_awaited_once_with(i18n.get(
            "commands.settings.switched_mode", mode=i18n.get(f"commands.settings.mode_{new}")), show_alert=False)

    @pytest.mark.parametrize("minutes", ["15", "45", "240"])
    async def test_any_interval_in_range_is_saved(self, minutes):
        d = _deps()
        callback = await _select(d, "interval", minutes)

        d.user_service.update_setting.assert_awaited_once_with(USER_ID, "review_interval_minutes", int(minutes))
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

        d.user_service.update_setting.assert_not_awaited()
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

        d.user_service.update_setting.assert_awaited_once_with(USER_ID, field, code)
        label = "primary_label" if field == "primary_language" else "secondary_label"
        message.reply.assert_awaited_once_with(i18n.get(
            "commands.settings.prompts.success_lang", type=i18n.get(f"commands.settings.prompts.{label}"),
            lang=get_language_name(code), flag=get_language_flag(code)))
        d.state.clear.assert_awaited_once()
        # The menu shows the language just chosen.
        message.answer.assert_awaited_once_with(
            i18n.get("commands.settings.sections.language"),
            reply_markup=get_language_settings_keyboard(user.model_copy(update={field: code})))

    async def test_secondary_none_is_confirmed_with_localized_none(self):
        d = _deps(state_name=SettingsPrompts.waiting_secondary_lang.state)
        message = await _answer_prompt(d, "none")

        d.user_service.update_setting.assert_awaited_once_with(USER_ID, "secondary_language", "none")
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

        d.user_service.update_setting.assert_not_awaited()
        message.reply.assert_awaited_once_with(
            i18n.get("commands.settings.prompts.invalid_lang"), reply_markup=get_language_settings_keyboard(user))
        d.state.clear.assert_awaited_once()


class TestReplyButtons:

    @pytest.mark.parametrize("was_active, button, key", [
        (True, "messages.buttons.pause_learning", "messages.notifications.paused"),
        (False, "messages.buttons.resume_learning", "messages.notifications.resumed"),
    ])
    async def test_pause_resume_toggles_and_swaps_button(self, was_active, button, key):
        d = _deps(_user(is_active=was_active))
        message = _message(i18n.get(button))
        await reply_commands.handle_status_change(message, settings_use_cases=d.settings_use_cases)

        d.user_service.toggle_active_status.assert_awaited_once_with(USER_ID)
        assert d.stored["user"].is_active is not was_active
        message.answer.assert_awaited_once_with(
            i18n.get(key), reply_markup=get_reply_settings_keyboard(not was_active))

    async def test_close_removes_the_reply_keyboard(self):
        message = _message(i18n.get("messages.buttons.close_settings"))
        await reply_commands.handle_close_settings(message)

        call = message.answer.await_args
        assert call.args == (i18n.get("commands.settings.closed"),)
        assert isinstance(call.kwargs["reply_markup"], ReplyKeyboardRemove)
