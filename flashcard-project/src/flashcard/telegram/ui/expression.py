from __future__ import annotations

from flashcard.schemas.expression import ExpressionCard
from flashcard.settings import settings

LINE_SEP = "\u2508" * 12


def _learning_definition_label() -> str:
    return f"{settings.LEARNING_LANGUAGE_FLAG} Def"


def _learning_example_label() -> str:
    return "🧩 Example"


def render_expression_card(card: ExpressionCard) -> dict[str, object]:
    if not card.success:
        line1 = f"{card.note or 'Expression not clear'}"
        return {"success": False, "content": line1}

    line1 = f"{_learning_definition_label()}: {card.learning_definition}".strip()

    t1 = card.translations[0] if len(card.translations) > 0 else None
    t2 = card.translations[1] if len(card.translations) > 1 else None

    line2 = f"{t1.label}: {t1.text}" if t1 else ""
    line3 = f"{t2.label}: {t2.text}" if t2 else ""
    line4 = f'{_learning_example_label()}: "{card.learning_example}"'

    lines = [line1, line2, line3, line4]
    return {"success": True, "content": "\n".join(filter(None, lines))}


def format_review_message(
    card: ExpressionCard,
    value: str,
    direction: str = "forward",
) -> str:
    """
    Formats the review message for the /get command.

    Direction: 'forward' (standard) or 'reverse' (dual mode).
    """
    translations_str = ""
    for trans in card.translations:
        translations_str += f"{trans.label}: {trans.text}\n"

    if direction == "reverse":
        # Reverse Mode: Show Meaning -> Hide Target Word + Example
        # Question: Definition or Translation
        # Let's prefer Definition if available, else Translation
        
        question_part = ""
        if card.learning_definition:
            question_part = f"{_learning_definition_label()}: {card.learning_definition}"
        elif translations_str:
            question_part = translations_str.strip()
        else:
            question_part = "???"

        # Spoiler: expression value, translations, and learning-language example.

        spoiler_content = f"""
🎯 Expression: <b>{value}</b>
{translations_str.strip()}
{_learning_example_label()}: "{card.learning_example or ''}"
""".strip()

        return (
            f"🔄 Reverse Review 🔄\n{LINE_SEP}\n{question_part}\n"
            f"{LINE_SEP}\n<tg-spoiler>{spoiler_content}</tg-spoiler>"
        )

    spoiler_content = f"""
{_learning_definition_label()}: {card.learning_definition or ''}
{translations_str.strip()}
{_learning_example_label()}: "{card.learning_example or ''}"
""".strip()

    return (
        f"Your picked expression: <b>{value}</b>\n{LINE_SEP}\n"
        f"<tg-spoiler>{spoiler_content}</tg-spoiler>"
    )
