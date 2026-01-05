from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

from flashcard.schemas.conjugations import ConjugationResponse
from flashcard.telegram.ui.factories.verb_callback import VerbCallback

PERSON_EMOJIS = {
    "io": "👤",
    "tu": "👥",
    "lui/lei": "👩‍💼",
    "noi": "👫",
    "voi": "👥",
    "loro": "👨‍👩‍👧‍👦"
}

def _cap(s: str) -> str:
    return s.capitalize() if s else ''

def _format_header(data: ConjugationResponse) -> str:
    verb = data.queried
    infinitivo = data.principal_forms.get('infinito', '—')
    gerundio = data.principal_forms.get('gerundio', '—')
    auxiliary = data.auxiliary if data.auxiliary else '—'
    
    return (
        f"🔤 Requested verb: <b>{verb}</b>\n"
        "________________________\n"
        f"♾️ Infinito (Infinitive): <b>{infinitivo}</b>\n"
        f"🌀 Gerundio (Gerund): <b>{gerundio}</b>\n"
        f"⚙️ Ausiliare (Auxiliary): <b>{auxiliary}</b>"
    )

def _format_footer() -> str:
    return "<i>👉 Altri tempi e modi (Other tenses and moods): usa i pulsanti qui sotto (use the buttons below).</i>"

def format_verb_message(data: ConjugationResponse) -> str:
    """
    Formats the verb conjugation data into an HTML message.
    matches the n8n template structure.
    """
    # Safely access Presente Indicativo
    try:
        presente = data.conjugations['indicativo']['presente']
        io = presente.get('io', '—')
        tu = presente.get('tu', '—')
        lui_lei = presente.get('lui, lei, Lei, egli', '—')
        noi = presente.get('noi', '—')
        voi = presente.get('voi', '—')
        loro = presente.get('loro, Loro, essi', '—')
    except KeyError:
        # Fallback if specific tense data is missing
        io = tu = lui_lei = noi = voi = loro = '?'

    # Construct the body with standardized emojis
    body = (
        "📚 Presente (Indicativo) — Present (Indicative)\n"
        f"{PERSON_EMOJIS['io']} io → <b>{io}</b>\n"
        f"{PERSON_EMOJIS['tu']} tu → <b>{tu}</b>\n"
        f"{PERSON_EMOJIS['lui/lei']} lui/lei → <b>{lui_lei}</b>\n"
        f"{PERSON_EMOJIS['noi']} noi → <b>{noi}</b>\n"
        f"{PERSON_EMOJIS['voi']} voi → <b>{voi}</b>\n"
        f"{PERSON_EMOJIS['loro']} loro → <b>{loro}</b>"
    )

    return f"{_format_header(data)}\n________________________\n\n{body}\n\n{_format_footer()}"

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

def format_verb_conjugation(data: ConjugationResponse, mood: str, tense: str) -> str:
    """
    Formats the specific mood/tense conjugation view.
    Matches the n8n logic for 'build html' node.
    """
    
    conj = data.conjugations
    
    if mood not in conj or tense not in conj[mood]:
        return (
            f"<b>⚠️ Non trovato</b>\n"
            f"Richiesta: {_cap(mood)} → {_cap(tense)}\n\n"
            "Prova un altro tempo o modo."
        )

    t = conj[mood][tense]
    lines = []
    
    if mood == 'imperativo':
        # Special order and labels for Imperativo
        order = ["(tu)", "(Lei)", "(noi)", "(voi)", "(Loro)"]
        labels = {"(tu)": "tu", "(Lei)": "Lei", "(noi)": "noi", "(voi)": "voi", "(Loro)": "Loro"}
        
        for k in order:
             label = labels.get(k, k)
             val = t.get(k, '—')
             lines.append(f"👉 {label} → <b>{val}</b>")
    else:
        # Standard person mapping
        mapping = [
            ("io", "io"),
            ("tu", "tu"),
            ("lui, lei, Lei, egli", "lui/lei"),
            ("noi", "noi"),
            ("voi", "voi"),
            ("loro, Loro, essi", "loro")
        ]
        
        for key, label in mapping:
            val = t.get(key, '—')
            # Use emoji from PERSON_EMOJIS if available, fallback to 👤
            emoji = PERSON_EMOJIS.get(label, "👤")
            lines.append(f"{emoji} {label} → <b>{val}</b>")

    html_parts = [
        _format_header(data),
        "________________________",
        "",
        f"📚 {_cap(mood)} - {_cap(tense)}",
    ]
    
    html_parts.extend(lines)
    
    html_parts.extend([
        "",
        _format_footer()
    ])
    
    return "\n".join(html_parts)