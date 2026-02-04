from __future__ import annotations

from flashcard.schemas.expression import ExpressionCard


def render_expression_card(card: ExpressionCard) -> Dict[str, str]:
    # Always 4 lines (for UX consistency)
    if not card.success:
        line1 = f"{card.note_it or 'Parola non chiara'}"
        ### add suggestions if not in note_it
        return {"success": False, "content": line1}

    # success path
    line1 = f"🇮🇹 Def: {card.def_it}".strip()

    # translations: expect 2, but guard anyway
    t1 = card.translations[0] if len(card.translations) > 0 else None
    t2 = card.translations[1] if len(card.translations) > 1 else None

    line2 = f"{t1.label}: {t1.text}" if t1 else ""
    line3 = f"{t2.label}: {t2.text}" if t2 else ""
    line4 = f'🧩 Esempio: "{card.example_it}"'

    lines = [line1, line2, line3, line4]
    return {"success": True, "content": "\n".join(filter(None, lines))}


def format_review_message(card: ExpressionCard, value: str, direction: str = "forward") -> str:
    """
    Formats the review message for the /get command.
    Includes the 'Your picked expression' header and spoiler content.
    Direction: 'forward' (Std) or 'reverse' (Dual Mode)
    """
    translations_str = ""
    for trans in card.translations:
        translations_str += f"{trans.label}: {trans.text}\n"
    
    if direction == "reverse":
        # Reverse Mode: Show Meaning -> Hide Target Word + Example
        # Question: Definition or Translation
        # Let's prefer Definition if available, else Translation
        
        question_part = ""
        if card.def_it:
             question_part = f"🇮🇹 Def: {card.def_it}"
        elif translations_str:
             question_part = translations_str.strip()
        else:
             question_part = "???"

        # Spoiler: The actual word (value) + translations (if def was question) or def (if trans was question) + example
        # Actually user requirement: "Question = def_it (Italian Def) or Translation (e.g. English), Spoiler = norm + example_it."
        
        # We can put everything else in spoiler to be safe
        spoiler_content = f"""
🎯 Expression: "{value}"
{translations_str.strip()}
🧩 Esempio: "{card.example_it or ''}"
""".strip()

        text = f"🔄 Reverse Review 🔄 \n{question_part}\n-----------\n<tg-spoiler>{spoiler_content}</tg-spoiler>"

    else:
        # Forward Mode (Standard): Show Word -> Hide Meaning
        spoiler_content = f"""
🇮🇹 Def: {card.def_it or ''}
{translations_str.strip()}
🧩 Esempio: "{card.example_it or ''}"
""".strip()

        text = f"Your picked expression: <b>{value}</b>\n-----------\n<tg-spoiler>{spoiler_content}</tg-spoiler>"
        
    return text
