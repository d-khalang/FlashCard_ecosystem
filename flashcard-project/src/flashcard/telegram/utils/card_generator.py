from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.telegram.utils.lang_labels import label_for
from flashcard.schemas.expression import ExpressionCard

# Defaults
DEFAULT_LEVEL = "B1"
DEFAULT_LANGS = ["en", "fa"]

async def generate_and_render_card(
    llm_service: LLMService,
    text: str,
) -> tuple[str, bool, ExpressionCard]:
    """
    Generates an expression card using LLMService and returns the rendered text, success status, and the card object.
    
    Args:
        llm_service: Instance of LLMService.
        text: Input text (raw or normalized).
        
    Returns:
        tuple[str, bool, ExpressionCard]: (rendered_text, success, card_object)
    """
    # TODO later: load from DB by user_id/chat_id
    level = DEFAULT_LEVEL
    langs = DEFAULT_LANGS
    
    lang1_code = langs[0]
    lang2_code = langs[1] if len(langs) > 1 else ""
    lang1_label = label_for(lang1_code)
    lang2_label = label_for(lang2_code) if lang2_code else ""

    card = await llm_service.generate_expression_card(
        raw=text,
        level=level,
        lang1_code=lang1_code,
        lang2_code=lang2_code,
        lang1_label=lang1_label,
        lang2_label=lang2_label,
    )

    rendered = render_expression_card(card)
    success = rendered.get("success", False)
    content = rendered.get("content", "")
    
    return content, success, card
