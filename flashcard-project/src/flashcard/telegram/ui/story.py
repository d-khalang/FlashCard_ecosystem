from flashcard.schemas.story import StoryResponse
from flashcard.telegram.utils.lang_labels import label_for

def format_story_messages(story_response: StoryResponse, target_lang: str = "en") -> list[str]:
    """
    Formats the story response into a list of messages to be sent sequentially.
    Each paragraph consists of two messages:
    1. The Italian text.
    2. The translation (hidden behind a spoiler) with the language flag.
    """
    messages = []
    lang_flag = label_for(target_lang)
    
    for paragraph in story_response.paragraphs:
        # 1. Italian Paragraph
        messages.append(paragraph.italian_text)
        
        # 2. Translation with spoiler
        translation_text = f"{lang_flag} <tg-spoiler>{paragraph.translation}</tg-spoiler>"
        messages.append(translation_text)
        
    return messages
