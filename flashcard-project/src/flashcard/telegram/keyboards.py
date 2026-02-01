# src/flashcard/telegram/keyboards.py
from aiogram.types import (InlineKeyboardMarkup, ReplyKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback
from flashcard.schemas.conjugations import ConjugationResponse
from flashcard.services.i18n import i18n
from flashcard.schemas.languages import get_language_flag, get_language_name

def expression_action_kb(norm: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=i18n.get("messages.buttons.save"), callback_data=f"save:{norm}")
    builder.button(text=i18n.get("messages.buttons.regenerate"), callback_data=f"regen:{norm}")
    return builder.as_markup()


def get_verb_keyboard(data: ConjugationResponse) -> InlineKeyboardMarkup:
    verb = data.queried
    url = data.url
    
    # 1. Initialize the Builder
    builder = InlineKeyboardBuilder()

    # --- INDICATIVO SECTION ---
    # Header
    builder.button(text="🧭 INDICATIVO", callback_data="noop|hdr|indicativo")
    # Row: Presente, Imperfetto
    builder.button(text="Presente", callback_data=VerbCallback(mood="indicativo", tense="presente", verb=verb))
    builder.button(text="Imperfetto", callback_data=VerbCallback(mood="indicativo", tense="imperfetto", verb=verb))
    # Row: Pass. remoto, Fut. semplice
    builder.button(text="Pass. remoto", callback_data=VerbCallback(mood="indicativo", tense="passato remoto", verb=verb))
    builder.button(text="Fut. semplice", callback_data=VerbCallback(mood="indicativo", tense="futuro semplice", verb=verb))

    # --- TEMPI COMPOSTI SECTION ---
    # Header
    builder.button(text="⏱️ TEMPI COMPOSTI", callback_data="noop|hdr|composti")
    # Row: Pass. prossimo, Trap. prossimo
    builder.button(text="Pass. prossimo", callback_data=VerbCallback(mood="tempi composti", tense="passato prossimo", verb=verb))
    builder.button(text="Trap. prossimo", callback_data=VerbCallback(mood="tempi composti", tense="trapassato prossimo", verb=verb))
    # Row: Trap. remoto, Fut. anteriore
    builder.button(text="Trap. remoto", callback_data=VerbCallback(mood="tempi composti", tense="trapassato remoto", verb=verb))
    builder.button(text="Fut. anteriore", callback_data=VerbCallback(mood="tempi composti", tense="futuro anteriore", verb=verb))

    # --- CONGIUNTIVO SECTION ---
    # Header
    builder.button(text="🧠 CONGIUNTIVO", callback_data="noop|hdr|congiuntivo")
    # Row: Presente, Imperfetto
    builder.button(text="Presente", callback_data=VerbCallback(mood="congiuntivo", tense="presente", verb=verb))
    builder.button(text="Imperfetto", callback_data=VerbCallback(mood="congiuntivo", tense="imperfetto", verb=verb))
    # Row: Passato, Trapassato
    builder.button(text="Passato", callback_data=VerbCallback(mood="congiuntivo", tense="passato", verb=verb))
    builder.button(text="Trapassato", callback_data=VerbCallback(mood="congiuntivo", tense="trapassato", verb=verb))

    # --- CONDIZIONALE SECTION ---
    # Header
    builder.button(text="🤔 CONDIZIONALE", callback_data="noop|hdr|condizionale")
    # Row: Presente, Passato
    builder.button(text="Presente", callback_data=VerbCallback(mood="condizionale", tense="presente", verb=verb))
    builder.button(text="Passato", callback_data=VerbCallback(mood="condizionale", tense="passato", verb=verb))

    # --- IMPERATIVO SECTION ---
    # Header/Item
    builder.button(text="📣 IMPERATIVO - Presente", callback_data=VerbCallback(mood="imperativo", tense="presente", verb=verb))

    # --- URL SECTION ---
    builder.button(text="📖 Tabella completa sul web", url=url)

    # 2. Define the Grid Layout
    builder.adjust(
        1,       # Indicativo Header
        2, 2,    # The 4 indicativo items (split into 2 rows of 2)
        1,       # Tempi Composti Header
        2, 2,    # The 4 tempi composti items (split into 2 rows of 2)
        1,       # Congiuntivo Header
        2, 2,    # The 4 congiuntivo items
        1,       # Condizionale Header
        2,       # The 2 condizionale items
        1,       # Imperativo
        1        # URL button
    )

    return builder.as_markup()

def get_review_keyboard(expression_id: str, direction: str = "forward") -> InlineKeyboardMarkup:
    # Let's use 'fwd' and 'rev'.
    
    dir_code = "rev" if direction == "reverse" else "fwd"
    
    builder = InlineKeyboardBuilder()
    
    # Row 1: 0 - I had no idea
    builder.button(text="0 - I had no idea", callback_data=f"grade:{expression_id}:0:{dir_code}")
    
    # Row 2: 1, 2, 3, 4
    for i in range(1, 5):
        builder.button(text=str(i), callback_data=f"grade:{expression_id}:{i}:{dir_code}")
        
    # Row 3: 5 - Known like family
    builder.button(text="5 - Known like family", callback_data=f"grade:{expression_id}:5:{dir_code}")
    
    builder.adjust(1, 4, 1)
    return builder.as_markup()

def get_reply_settings_keyboard(is_active: bool) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    
    # Toggle button
    if is_active:
        text = i18n.get("messages.buttons.pause_learning")
    else:
        text = i18n.get("messages.buttons.resume_learning")
        
    builder.button(text=text)
    builder.button(text=i18n.get("messages.buttons.close_settings"))  
    builder.adjust(1, 1)
    
    return builder.as_markup(resize_keyboard=True)

# -------------------------------------------------------------------------
# Settings Keyboards
# -------------------------------------------------------------------------

def get_main_settings_keyboard(user_data: dict = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # 🌍 Language & Level
    builder.button(text=i18n.get("commands.settings.menu_options.language"), callback_data=SettingsCallback(action="nav", section="lang_menu").pack())
    
    # 🔔 Schedule/Interval
    builder.button(text=i18n.get("commands.settings.menu_options.interval"), callback_data=SettingsCallback(action="nav", section="interval").pack())
    
    # 🔄 Review Mode (Standard/Dual)
    mode = "Standard"
    if user_data:
        mode = user_data.get("review_mode", "standard").capitalize()
        if mode == "Dual": mode = "Dual 🔄" 
        else: mode = "Standard ➡️"
        
    # We use a toggle action effectively
    builder.button(text=f"Mode: {mode}", callback_data=SettingsCallback(action="select", section="review_mode", value="toggle").pack())

    # 🔑 API Config
    builder.button(text=i18n.get("commands.settings.menu_options.api"), callback_data=SettingsCallback(action="nav", section="api").pack())
    
    builder.adjust(2, 1, 1) # Language|Interval, Mode, API
    return builder.as_markup()

def get_language_settings_keyboard(current_data: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Get Current Settings
    curr_p = current_data.get("primary_language", "en")
    curr_s = current_data.get("secondary_language")
    curr_l = current_data.get("target_level", "A2")
    
    # 1. Primary Language (Always has a value or default)
    flag_p = get_language_flag(curr_p)
    btn_p = f"{flag_p} {i18n.get('commands.settings.buttons.set_primary')}"
    
    builder.button(
        text=btn_p, 
        callback_data=SettingsCallback(action="nav", section="set_lang_p").pack()
    )
    
    # 2. Secondary Language (Can be None)
    if curr_s and curr_s.lower() != "none":
        flag_s = get_language_flag(curr_s)
    else:
        flag_s = "⚪" # Placeholder for None
        
    btn_s = f"{flag_s} {i18n.get('commands.settings.buttons.set_secondary')}"
    
    builder.button(
        text=btn_s, 
        callback_data=SettingsCallback(action="nav", section="set_lang_s").pack()
    )

    # 3. Target Level
    btn_l = f"{i18n.get('commands.settings.buttons.set_level')}: {curr_l}"
    builder.button(
        text=btn_l,
        callback_data=SettingsCallback(action="nav", section="set_level").pack()
    )

    # 4. Back
    builder.button(
        text=i18n.get("commands.settings.buttons.back"), 
        callback_data=SettingsCallback(action="nav", section="main").pack()
    )
    
    builder.adjust(1)
    return builder.as_markup()

def get_level_selection_keyboard(current_level: str = "A2") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    
    for level in levels:
        text = f"{level} {'✅' if level == current_level else ''}"
        builder.button(
            text=text, 
            callback_data=SettingsCallback(action="select", section="target_level", value=level).pack()
        )
        
    builder.button(
        text=i18n.get("commands.settings.buttons.back"),
        callback_data=SettingsCallback(action="nav", section="lang_menu").pack()
    )
        
    builder.adjust(3, 3, 1)
    return builder.as_markup()

def get_interval_settings_keyboard(current_minutes: int = 30) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    options = [30, 60, 90, 120]
    
    for opt in options:
        text = f"{opt} min {'✅' if current_minutes == opt else ''}"
        builder.button(text=text, callback_data=SettingsCallback(action="select", section="interval", value=str(opt)).pack())
        
    builder.button(text=i18n.get("commands.settings.buttons.back"), callback_data=SettingsCallback(action="nav", section="main").pack())
    
    builder.adjust(2, 2, 1)
    return builder.as_markup()