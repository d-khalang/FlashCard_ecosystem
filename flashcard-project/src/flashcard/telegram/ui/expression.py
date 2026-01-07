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

    line2 = f"{t1.label}: {t1.text}" if t1 else "—"
    line3 = f"{t2.label}: {t2.text}" if t2 else "—"
    line4 = f'🧩 Esempio: "{card.example_it}"'

    return {"success": True, "content": "\n".join([line1, line2, line3, line4])}
