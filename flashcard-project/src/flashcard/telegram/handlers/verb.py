import html
from aiogram import Router, Bot, flags
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatAction
from contextlib import suppress
from aiogram.exceptions import TelegramBadRequest

from flashcard.settings import settings

from flashcard.services.verb import VerbService
from flashcard.telegram.ui.verb import format_verb_conjugation, format_verb_message
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.services.i18n import i18n
from flashcard.services.consumption import ConsumptionService
from flashcard.telegram.keyboards import get_verb_keyboard
from flashcard.telegram.helpers.callback_utils import safe_answer_callback
from flashcard.utils.logger import get_logger, notify_admin_with_trace

logger = get_logger(__name__)
router = Router()


@router.message(Command("verb"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_verb(message: Message, verb_service: VerbService, consumption_service: ConsumptionService, logger_bot: Bot):
    """
    Handle /verb command.
    """
    # 1. Extract verb
    extracted_verb = verb_service.extract_verb(message.text)
    
    if not extracted_verb:
        await message.answer(i18n.get("commands.verb.instruction"))
        return
    
    # 2. Validate verb format
    if not verb_service.is_valid_verb(extracted_verb):
        logger.warning(f"Invalid verb: {extracted_verb}")
        await message.answer(i18n.get("commands.verb.invalid"))
        return

    # 3. Get verb data (DB or API)
    # Give feedback to user that we are processing
    status_msg = await message.answer(i18n.get("commands.verb.searching", verb=extracted_verb))
    
    try:
        verb_data = await verb_service.get_verb_data(extracted_verb)
    except Exception as e:
        logger.error(f"Verb data retrieval error for '{extracted_verb}': {e}")
        await notify_admin_with_trace(logger_bot, f"Verb data error for '{extracted_verb}' (user {message.from_user.id}): {str(e)}")
        await message.answer(i18n.get("commands.verb.api_error"))
        return
     
    if not verb_data:
        # Not found in DB or API
        error_text = i18n.get("commands.verb.api_error")
        await message.answer(error_text)
        return

    # Editing searching message
    # 4. Return success response
    formatted_text = format_verb_message(verb_data)
    keyboard = get_verb_keyboard(verb_data)
    
    await status_msg.edit_text(text=formatted_text, reply_markup=keyboard)
    
    # Track consumption (verb lookups always use system/third-party)
    await consumption_service.increment(message.from_user.id, "verb_lookups")


@router.callback_query(VerbCallback.filter())
async def handle_conjugation(callback: CallbackQuery, callback_data: VerbCallback, verb_service: VerbService):
    """
    Handle verb conjugation navigation callbacks.
    """
    verb = callback_data.verb
    mood = callback_data.mood
    tense = callback_data.tense
    
    # 1. Fetch verb data 
    # Since this is a callback, likely it's in DB.
    verb_data = await verb_service.get_verb_data(verb)
    
    if not verb_data:
        # Edge case: Verb somehow missing?
        await safe_answer_callback(callback, i18n.get("callbacks.verb.not_found"), show_alert=True)
        return

    # 2. Format specific view
    html_text = format_verb_conjugation(verb_data, mood, tense)
    
    # 3. Edit message    
    # 'suppress' handles the crash if the user clicks the same button twice (content doesn't change)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            text=html_text,
            # Pass the same keyboard back if you want the buttons to stay
            reply_markup=callback.message.reply_markup
        )
        
        await safe_answer_callback(callback, i18n.get("callbacks.verb.updated"))
