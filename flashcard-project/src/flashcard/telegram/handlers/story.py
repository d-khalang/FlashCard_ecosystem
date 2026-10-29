from aiogram import Router, flags
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.app.quota import QuotaExceeded
from flashcard.app.story import EmptyStory, NoWords, Story, StoryUseCases
from flashcard.services.i18n import I18nService
from flashcard.telegram.ui.story import format_story_messages
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


@router.message(Command("story"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_story(message: Message, story_use_cases: StoryUseCases, i18n: I18nService):
    # Flag: -l for a longer story.
    long = "-l" in (message.text or "").split()[1:]

    async def notify_writing(count: int) -> None:
        await message.answer(i18n.get("commands.story.writing", count=count))

    result = await story_use_cases.write(message.from_user.id, long=long, on_writing=notify_writing)

    if isinstance(result, Story):
        for text in format_story_messages(result.story, target_lang=result.translation_language):
            await message.answer(text)
    elif isinstance(result, NoWords):
        await message.answer(i18n.get("commands.story.no_expressions"))
    elif isinstance(result, EmptyStory):
        await message.answer(i18n.get("commands.story.generation_error"))
    elif isinstance(result, QuotaExceeded):
        await message.answer(i18n.get(
            "messages.errors.quota_exceeded", type="story", tier=result.tier, limit=result.limit))
