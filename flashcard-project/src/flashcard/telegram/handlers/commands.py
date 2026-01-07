import logging
from aiogram import Router, flags
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.services.i18n import i18n
from flashcard.services.verb import VerbService


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    # Retrieve welcome message from I18n service
    welcome_text = i18n.get("start.welcome")
    await message.answer(welcome_text)
    #TODO: translations and detailed explanations be added by buttons
    # also video, possibly in reply markup


@router.message(Command("get"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_get(message: Message):
    await message.answer("get command")


@router.message(Command("import"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_import(message: Message):
    await message.answer("import command")


@router.message(Command("list_my_flashcards"))
async def cmd_list_my_flashcards(message: Message):
    await message.answer("list_my_flashcards command")


@router.message(Command("story"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_story(message: Message):
    await message.answer("story command")


@router.message(Command("verb"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_verb(message: Message, verb_service: VerbService):
    """
    Handle /verb command.
    """
    # 1. Extract verb
    extracted_verb = verb_service.extract_verb(message.text)
    
    if not extracted_verb:
        await message.answer(i18n.get("verb.instruction"))
        return
    
    # 2. Validate verb format
    if not verb_service.is_valid_verb(extracted_verb):
        logger.warning(f"Invalid verb: {extracted_verb}")
        await message.answer(i18n.get("verb.invalid"))
        return

    # 3. Get verb data (DB or API)
    # Give feedback to user that we are processing
    status_msg = await message.answer(f"Searching for verb: {extracted_verb}...")
    
    verb_data = await verb_service.get_verb_data(extracted_verb)
     
    if not verb_data:
        # Not found in DB or API, or API error
        error_text = i18n.get("verb.api_error") # Or "not found" specific message
        await message.answer(error_text)
        return

    # Editing searching message
    # 4. Return success response
    from flashcard.telegram.ui.verb import format_verb_message
    from flashcard.telegram.keyboards import get_verb_keyboard
    
    formatted_text = format_verb_message(verb_data)
    keyboard = get_verb_keyboard(verb_data)
    
    await status_msg.edit_text(text=formatted_text, reply_markup=keyboard)


