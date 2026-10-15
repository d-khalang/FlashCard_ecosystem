from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, ForceReply
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from flashcard.telegram.helpers.callback_utils import safe_answer_callback

from flashcard.app.settings import SettingsUseCases
from flashcard.schemas.user import NO_LANGUAGE
from flashcard.services.i18n import i18n
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback
from flashcard.telegram.keyboards import (
    get_reply_settings_keyboard,
    get_main_settings_keyboard,
    get_language_settings_keyboard,
    get_interval_settings_keyboard,
    get_level_selection_keyboard,
    review_mode_label,
)
from flashcard.telegram.states.settings import SettingsPrompts
from flashcard.schemas.languages import get_language_flag, get_language_name
from flashcard.schemas.user import UserDB

router = Router()

@router.message(Command("settings"))
async def cmd_settings(message: Message, settings_use_cases: SettingsUseCases):
    user_data = await settings_use_cases.get(message.from_user.id)

    # Send Main Inline Menu
    await message.answer(_get_settings_menu_text(user_data), reply_markup=get_main_settings_keyboard(user_data))

    # also ensure Reply Keyboard is present (optional, user might have closed it)
    quick_kb = get_reply_settings_keyboard(user_data.is_active)
    await message.answer(i18n.get("commands.settings.controls"), reply_markup=quick_kb)


@router.callback_query(SettingsCallback.filter(F.action == "nav"))
async def handle_settings_nav(callback: CallbackQuery, callback_data: SettingsCallback,
                              settings_use_cases: SettingsUseCases, state: FSMContext):
    user_id = callback.from_user.id
    section = callback_data.section

    if section == "main":
        user_data = await settings_use_cases.get(user_id)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(
                text=_get_settings_menu_text(user_data),
                reply_markup=get_main_settings_keyboard(user_data)
            )

    elif section == "lang_menu":
        user_data = await settings_use_cases.get(user_id)
        text = i18n.get("commands.settings.sections.language")
        kb = get_language_settings_keyboard(user_data)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=text, reply_markup=kb)

    elif section == "set_lang_p":
        await state.set_state(SettingsPrompts.waiting_primary_lang)
        text = i18n.get("commands.settings.prompts.primary_lang")
        await callback.message.answer(text, reply_markup=ForceReply(
            input_field_placeholder="e.g. en, english, spanish, es, ...",
            selective=True))

    elif section == "set_lang_s":
        await state.set_state(SettingsPrompts.waiting_secondary_lang)
        text = i18n.get("commands.settings.prompts.secondary_lang")
        await callback.message.answer(text, reply_markup=ForceReply(
            input_field_placeholder="e.g. en, english, es, none, ...",
            selective=True))

    elif section == "set_level":
        user_data = await settings_use_cases.get(user_id)
        text = i18n.get("commands.settings.prompts.level_select")
        kb = get_level_selection_keyboard(user_data.target_level)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=text, reply_markup=kb)

    elif section == "interval":
        user_data = await settings_use_cases.get(user_id)
        text = i18n.get("commands.settings.sections.interval")
        kb = get_interval_settings_keyboard(user_data.review_interval_minutes)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")

    elif section == "api":
        await safe_answer_callback(callback, i18n.get("commands.settings.sections.api"), show_alert=True)
        return

    await safe_answer_callback(callback)


@router.callback_query(SettingsCallback.filter(F.action == "select"))
async def handle_settings_select(callback: CallbackQuery, callback_data: SettingsCallback,
                                 settings_use_cases: SettingsUseCases):
    user_id = callback.from_user.id
    section = callback_data.section
    value = callback_data.value

    try:
        if section == "target_level":
            level = await settings_use_cases.set_level(user_id, value)
            kb = get_level_selection_keyboard(level)

        elif section == "interval":
            minutes = await settings_use_cases.set_interval(user_id, int(value or ""))
            kb = get_interval_settings_keyboard(minutes)

        elif section == "review_mode":
            if value == "toggle":  # menus sent before the button named its target mode
                new_mode = await settings_use_cases.toggle_review_mode(user_id)
            else:
                new_mode = await settings_use_cases.set_review_mode(user_id, value)
            # Redraw the whole menu, since it shows the mode.
            user_data = await settings_use_cases.get(user_id)
            with suppress(TelegramBadRequest):
                await callback.message.edit_text(
                    text=_get_settings_menu_text(user_data), reply_markup=get_main_settings_keyboard(user_data))
            await safe_answer_callback(
                callback, i18n.get("commands.settings.switched_mode", mode=review_mode_label(new_mode)))
            return

        else:
            raise ValueError(f"Unknown settings section: {section!r}")

    except ValueError:
        # Values come from buttons, so this means stale or forged callback data.
        await safe_answer_callback(callback, i18n.get("commands.settings.invalid_value"), show_alert=True)
        return

    with suppress(TelegramBadRequest):
        await callback.message.edit_reply_markup(reply_markup=kb)
    await safe_answer_callback(callback, i18n.get("commands.settings.saved"))


@router.message(SettingsPrompts.waiting_primary_lang)
@router.message(SettingsPrompts.waiting_secondary_lang)
async def answer_setting_prompt(message: Message, state: FSMContext, settings_use_cases: SettingsUseCases):
    user_id = message.from_user.id
    is_primary = await state.get_state() == SettingsPrompts.waiting_primary_lang.state
    # The prompt is answered once, whether or not the input is valid.
    await state.clear()

    try:
        if is_primary:
            code = await settings_use_cases.set_primary_language(user_id, message.text)
        else:
            code = await settings_use_cases.set_secondary_language(user_id, message.text)
    except ValueError:
        user_data = await settings_use_cases.get(user_id)
        await message.reply(i18n.get("commands.settings.prompts.invalid_lang"),
                            reply_markup=get_language_settings_keyboard(user_data))
        return

    type_label = i18n.get(
        "commands.settings.prompts.primary_label" if is_primary else "commands.settings.prompts.secondary_label")
    await message.reply(i18n.get("commands.settings.prompts.success_lang",
                                 type=type_label, lang=_language_name(code), flag=_language_flag(code)))

    # Show the language menu again
    user_data = await settings_use_cases.get(user_id)
    await message.answer(i18n.get("commands.settings.sections.language"),
                         reply_markup=get_language_settings_keyboard(user_data))


def _language_name(code) -> str:
    return i18n.get("commands.settings.no_language") if _is_no_language(code) else get_language_name(code)


def _language_flag(code) -> str:
    return "⚪" if _is_no_language(code) else get_language_flag(code)


def _is_no_language(code) -> bool:
    return not code or code.lower() == NO_LANGUAGE


def _get_settings_menu_text(user_data: UserDB) -> str:
    primary_lang_code = user_data.primary_language
    primary_lang = f"{get_language_flag(primary_lang_code)} {get_language_name(primary_lang_code)}"

    secondary_lang_code = user_data.secondary_language
    if _is_no_language(secondary_lang_code):
        secondary_lang = i18n.get("commands.settings.no_language")
    else:
        secondary_lang = f"{get_language_flag(secondary_lang_code)} {get_language_name(secondary_lang_code)}"

    status_key = "commands.settings.status_active" if user_data.is_active else "commands.settings.status_paused"
    review_interval_minutes = user_data.review_interval_minutes

    lines = [
        i18n.get("commands.settings.menu.heading") + "\n",
        i18n.get("commands.settings.menu.status", status=i18n.get(status_key)),
        i18n.get("commands.settings.menu.primary_lang", primary_lang=primary_lang),
        i18n.get("commands.settings.menu.secondary_lang", secondary_lang=secondary_lang),
        i18n.get("commands.settings.menu.target_level", target_level=user_data.target_level),
        i18n.get("commands.settings.menu.review_interval", review_interval_minutes=review_interval_minutes),
        i18n.get("commands.settings.menu.review_mode", review_mode=review_mode_label(user_data.review_mode)),
    ]
    return "\n".join(lines)
