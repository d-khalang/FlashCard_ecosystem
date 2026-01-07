from aiogram.types import (InlineKeyboardMarkup)

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.schemas.conjugations import ConjugationResponse

def expression_action_kb(norm: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Save", callback_data=f"save:{norm}")
    builder.button(text="Regen", callback_data=f"regen:{norm}")
    return builder.as_markup()

def get_reply_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Test1")
    builder.button(text="Test2")
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