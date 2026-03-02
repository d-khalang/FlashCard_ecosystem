from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, ForceReply
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from flashcard.services.user import UserService
from flashcard.services.i18n import i18n
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback
from flashcard.telegram.keyboards import (
    get_reply_settings_keyboard, 
    get_main_settings_keyboard, 
    get_language_settings_keyboard,
    get_interval_settings_keyboard,
    get_level_selection_keyboard
)
from flashcard.telegram.states.settings import SettingsPrompts
from flashcard.schemas.languages import normalize_language_input, get_language_flag, get_language_name
from flashcard.schemas.user import UserDB

router = Router()

@router.message(Command("settings"))
async def cmd_settings(message: Message, user_service: UserService):
    user_id = message.from_user.id
    
    # Get user data
    user_data = await user_service.get_user(user_id)
    is_active = user_data.is_active

    # Get Text
    text = _get_settings_menu_text(user_data)
    
    # Send Main Inline Menu
    await message.answer(text, reply_markup=get_main_settings_keyboard(user_data))
    
    # also ensure Reply Keyboard is present (optional, user might have closed it)
    quick_kb = get_reply_settings_keyboard(is_active)
    await message.answer(i18n.get("commands.settings.controls"), reply_markup=quick_kb)


@router.callback_query(SettingsCallback.filter(F.action == "nav"))
async def handle_settings_nav(callback: CallbackQuery, callback_data: SettingsCallback, user_service: UserService, state: FSMContext):
    user_id = callback.from_user.id
    section = callback_data.section
    
    if section == "main":
        user_data = await user_service.get_user(user_id)
        text = _get_settings_menu_text(user_data)
        
        await callback.message.edit_text(
            text=text,
            reply_markup=get_main_settings_keyboard(user_data)
        )
    
    elif section == "lang_menu":
        user_data = await user_service.get_user(user_id)
        text = i18n.get("commands.settings.sections.language")
        kb = get_language_settings_keyboard(user_data)
        await callback.message.edit_text(text=text, reply_markup=kb)
        
    elif section == "set_lang_p":
        await state.set_state(SettingsPrompts.waiting_primary_lang)
        text = i18n.get("commands.settings.prompts.primary_lang")
        await callback.message.answer(text, reply_markup=ForceReply(
            input_field_placeholder="e.g. en, english, spanish, es, ...",
            selective=True))
        await callback.answer()
        
    elif section == "set_lang_s":
        await state.set_state(SettingsPrompts.waiting_secondary_lang)
        text = i18n.get("commands.settings.prompts.secondary_lang")
        await callback.message.answer(text, reply_markup=ForceReply(
            input_field_placeholder="e.g. en, english, es, none, ...",
            selective=True))
        await callback.answer()
        
    elif section == "set_level":
        user_data = await user_service.get_user(user_id)
        current = user_data.target_level
        text = i18n.get("commands.settings.prompts.level_select")
        kb = get_level_selection_keyboard(current)
        await callback.message.edit_text(text=text, reply_markup=kb)
        
    elif section == "interval":
        user_data = await user_service.get_user(user_id)
        current = user_data.review_interval_minutes
        text = i18n.get("commands.settings.sections.interval")
        kb = get_interval_settings_keyboard(current)
        await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
        
    elif section == "api":
        text = i18n.get("commands.settings.sections.api")
        await callback.answer(text, show_alert=True)
        
    await callback.answer()


@router.callback_query(SettingsCallback.filter(F.action == "select"))
async def handle_settings_select(callback: CallbackQuery, callback_data: SettingsCallback, user_service: UserService):
    user_id = callback.from_user.id
    section = callback_data.section
    value = callback_data.value
    
    if section == "target_level":
        await user_service.update_setting(user_id, "target_level", value)
        kb = get_level_selection_keyboard(value)
        await callback.message.edit_reply_markup(reply_markup=kb)
        
    elif section == "interval":
        try:
            val_int = int(value)
            await user_service.update_setting(user_id, "review_interval_minutes", val_int)
            kb = get_interval_settings_keyboard(val_int)
            await callback.message.edit_reply_markup(reply_markup=kb)
        except ValueError:
            pass
            

    elif section == "review_mode":
        # Toggle Logic
        user_data = await user_service.get_user(user_id)
        current_mode = user_data.review_mode
        new_mode = "dual" if current_mode == "standard" else "standard"
        
        await user_service.update_setting(user_id, "review_mode", new_mode)
        
        # Update text and keyboard to reflect change
        user_data.review_mode = new_mode # local update for display
        text = _get_settings_menu_text(user_data)
        kb = get_main_settings_keyboard(user_data)
        
        await callback.message.edit_text(text=text, reply_markup=kb)
        await callback.answer(i18n.get("commands.settings.switched_mode", mode=new_mode.capitalize()))
        return # return early as we edited text
            
    await callback.answer(i18n.get("commands.settings.saved"))


@router.message(SettingsPrompts.waiting_primary_lang)
@router.message(SettingsPrompts.waiting_secondary_lang)
async def answer_setting_prompt(message: Message, state: FSMContext, user_service: UserService):
    input_text = message.text
    user_id = message.from_user.id
    current_state = await state.get_state()
    
    try:
        # Determine setting type
        is_primary = current_state == SettingsPrompts.waiting_primary_lang.state
        setting_key = "primary_language" if is_primary else "secondary_language"
        type_label = "Primary" if is_primary else "Secondary"

        # Validate Input
        lang_code = normalize_language_input(input_text, none_allowed=not is_primary)
        flag = get_language_flag(lang_code)
        name = get_language_name(lang_code)
        print(f"lang_code: {lang_code}, flag: {flag}, name: {name}")
        
        # Save
        await user_service.update_setting(user_id, setting_key, lang_code)
        
        # Confirmation
        msg = i18n.get("commands.settings.prompts.success_lang", type=type_label, lang=name, flag=flag)
        await message.reply(msg)
        
        # Clear State & Show Menu again
        await state.clear()
        
        # Optionally show the menu again
        user_data = await user_service.get_user(user_id)
        kb = get_language_settings_keyboard(user_data)
        await message.answer(i18n.get("commands.settings.sections.language"), reply_markup=kb)
        
    except ValueError:
        user_data = await user_service.get_user(user_id)
        await message.reply(i18n.get("commands.settings.prompts.invalid_lang"), reply_markup=get_language_settings_keyboard(user_data))
        await state.clear()


def _get_settings_menu_text(user_data: UserDB) -> str:
    is_active = user_data.is_active
    primary_lang_code = user_data.primary_language
    primary_lang = f"{get_language_flag(primary_lang_code)} {get_language_name(primary_lang_code)}"
    
    secondary_lang_code = user_data.secondary_language
    if secondary_lang_code and secondary_lang_code.lower() != "none":
        secondary_lang = f"{get_language_flag(secondary_lang_code)} {get_language_name(secondary_lang_code)}"
    else:
        secondary_lang = "None"
        
 
    target_level = user_data.target_level
    review_interval_minutes = user_data.review_interval_minutes

    # Get status text
    status_key = "commands.settings.status_active" if is_active else "commands.settings.status_paused"
    status_text = i18n.get(status_key)

    text = ""
    text += i18n.get("commands.settings.menu.heading") + "\n\n"
    text += i18n.get("commands.settings.menu.status", status=status_text) + "\n"
    text += i18n.get("commands.settings.menu.primary_lang", primary_lang=primary_lang) + "\n"
    text += i18n.get("commands.settings.menu.secondary_lang", secondary_lang=secondary_lang) + "\n"
    text += i18n.get("commands.settings.menu.target_level", target_level=target_level) + "\n"
    text += i18n.get("commands.settings.menu.review_interval", review_interval_minutes=review_interval_minutes) + "\n"
    
    review_mode = user_data.review_mode.capitalize()
    text += f"Review Mode: <b>🔄 {review_mode}</b>"
    
    return text

