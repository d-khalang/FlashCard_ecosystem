from aiogram import Router, Bot, flags
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.settings import settings
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.services.user import UserService
from flashcard.services.i18n import i18n
from flashcard.telegram.ui.story import format_story_messages
from flashcard.utils.logger import get_logger

import random

logger = get_logger(__name__)
router = Router()


@router.message(Command("story"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_story(message: Message, llm_service: LLMService, expression_service: ExpressionService, user_service: UserService, logger_bot: Bot):
    msg_text = message.text or ""
    args = msg_text.split()[1:] # Ignore command
    
    # Defaults
    story_length = "6-10 sentences"
    
    # Check for -l flag
    if "-l" in args:
        story_length = "10-16 sentences"
        
    # Get user expressions
    expressions = await expression_service.get_all_expressions(message.from_user.id)
    
    if not expressions:
        await message.answer(i18n.get("commands.story.no_expressions", "No expressions found. Add some first!"))
        return

    # Select words (Shuffle & Limit to 80)
    # If <= 80, use all. If > 80, shuffle and take 80.
    selected_words = expressions
    if len(expressions) > 80:
        random.shuffle(expressions)
        selected_words = expressions[:80]
        
        random.shuffle(expressions)
        selected_words = expressions[:80]
        
    await message.answer(i18n.get("commands.story.writing", count=len(selected_words)))

    ## TODO: Can be changed to calling a specific util for user level    
    user = await user_service.get_user(message.from_user.id)
    target_level = user.level
    
    try:
        story_response = await llm_service.generate_story(
            words=selected_words, 
            target_lang="en", # Configurable in future
            target_level=target_level,
            story_length=story_length
        )
    except Exception as e:
        logger.error(f"Story generation error: {e}")
        await logger_bot.send_message(settings.ADMIN_ID, f"Story generation error for user {message.from_user.id}: {e}")
        await message.answer(i18n.get("commands.story.generation_error"))
        return

    # Send paragraphs
    messages = format_story_messages(story_response, target_lang="en")
    
    for text in messages:
        await message.answer(text)
