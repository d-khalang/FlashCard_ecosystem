import asyncio
import logging
from aiogram import Router, flags
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ChatAction
from pydantic import ValidationError

from flashcard.services.i18n import i18n
from flashcard.services.verb import VerbService
from flashcard.schemas.verb_conjugations import ConjugationResponse

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
async def cmd_verb(message: Message, verb_service: VerbService):
    # Use Service Layer for validation logic
    extracted_verb = verb_service.extract_verb(message.text)
    
    if not extracted_verb:
        # logger.info(f"Message text: {message.text}")
        instruction_text = i18n.get("verb.instruction")
        await message.answer(instruction_text)
        return
    
    if not verb_service.is_valid_verb(extracted_verb):
        logger.info(f"Invalid verb: {extracted_verb}")
        error_text = i18n.get("verb.invalid")
        await message.answer(error_text)
        return

    # TODO: get verb from api
    await message.answer(f"Processing verb: {extracted_verb}")
    verb_dict = await verb_service.get_verb_from_db(extracted_verb)
    # await message.answer(f"Verb_dict: {verb_dict}")
    # logger.info(f"Verb_dict: {verb_dict}")

    if not verb_dict:
        # get from api
        await message.answer(f"Verb not found in db: {extracted_verb}")
        await verb_service.get_verb_from_api(extracted_verb)
        return

    try:
        verb_response = ConjugationResponse(**verb_dict.get("data", {}))
        await message.answer(f"Verb response: {verb_response.model_dump_json()}")
    except ValidationError as e:
        logger.error(f"Failed to validate verb response: {e}")
        await message.answer("Failed to validate verb response")
        return

    ### TODO: add schema for db version, validate the response, add insert to db, complete rollbacks also in verb service


