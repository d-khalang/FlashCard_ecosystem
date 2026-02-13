from aiogram import Bot, Router, F, flags
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatAction
from contextlib import suppress
from datetime import datetime

from flashcard.settings import settings
from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.telegram.ui.verb import format_verb_conjugation
from flashcard.services.verb import VerbService
from flashcard.services.expression import ExpressionService
from flashcard.services.i18n import i18n
from flashcard.telegram.utils.card_generator import generate_and_render_card
from flashcard.utils.logger import get_logger


logger = get_logger(__name__)
router = Router()


@router.callback_query(F.data.startswith("save:"))
async def handle_save(callback: CallbackQuery, expression_service: ExpressionService):
    # Format: save:{norm}
    norm = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    
    # Attempt to add expression via service
    saved = await expression_service.add_expression(user_id, norm)

    if saved:
        print("Saved to collection received!")
        await callback.answer(i18n.get("callbacks.save.success_message"), show_alert=True)
        # Edit message to show saved status
        # Just extra check, could be omitted
        original_text = callback.message.text or callback.message.caption or ""
        await callback.message.edit_text(f"{original_text}{i18n.get('callbacks.save.success_tag')}")
    else:
        # Duplicate case
        await callback.answer(i18n.get("callbacks.save.already_exists"), show_alert=True)

        # Get the current markup
        current_markup = callback.message.reply_markup

        # Check if markup and buttons exist (safety check)
        if current_markup and current_markup.inline_keyboard:
            # Create a shallow copy of the keyboard rows to avoid modifying the original object directly
            keyboard = [list(row) for row in current_markup.inline_keyboard]
            
            if keyboard and keyboard[0]:
                # Check if the first button is the save button
                if keyboard[0][0].callback_data.startswith("save:"):
                    keyboard[0].pop(0)
                    # If the row is now empty, remove the row itself
                    if not keyboard[0]:
                        keyboard.pop(0)
            
            # Apply the change
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))



@router.callback_query(F.data.startswith("regen:"))
@flags.chat_action(ChatAction.TYPING)
async def handle_regen(callback: CallbackQuery, llm_service: LLMService):
    callback_markup = callback.message.reply_markup
    await callback.message.edit_text(i18n.get("callbacks.regen.working"))

    expression = callback.data.split(":", 1)[1]

    text, success, card = await generate_and_render_card(llm_service, expression)

    if success:
        await callback.message.edit_text(
            text=text,
            reply_markup=callback_markup
        )
    else:
        await callback.message.edit_text(i18n.get("callbacks.regen.failed"))
   



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
        await callback.answer(i18n.get("callbacks.verb.not_found"), show_alert=True)
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
        
        await callback.answer(i18n.get("callbacks.verb.updated"))

@router.callback_query(GradeCallback.filter())
async def handle_grade(callback: CallbackQuery, callback_data: GradeCallback, expression_service: ExpressionService, logger_bot: Bot):
    """
    Handle grading callbacks: grade:{expression_id}:{grade}:{direction_code}
    direction_code: 'fwd' | 'rev' (optional, defaults to 'fwd' for backward compat)
    """
    try:    
        expression_id = callback_data.expression_id
        grade = callback_data.grade
        direction_code = callback_data.direction

        direction = "reverse" if direction_code == "rev" else "forward"
        
        user_id = callback.from_user.id
        
        updated_doc = await expression_service.grade_expression(user_id, expression_id, grade, direction)
        
        if updated_doc:
            value = updated_doc.get("value", "Unknown")
            await callback.message.edit_text(f"{callback.message.text}{i18n.get('callbacks.grade.rated', grade=grade)}")
            await callback.answer(i18n.get("callbacks.grade.success"))
        else:
            await callback.answer(i18n.get("callbacks.grade.error_missing"), show_alert=True)
            
    except ValueError:
        #TODO: Have a consistent schema for logging errors to logger bot
        await callback.answer(i18n.get("callbacks.grade.invalid_data"), show_alert=True)
        await logger_bot.send_message(settings.ADMIN_ID, f"Invalid callback data: {callback.data}")

    except Exception as e:
        logger.error(f"Error handling grade callback: {e}", exc_info=True)
        await callback.answer(i18n.get("callbacks.grade.error_generic"), show_alert=True)
        await logger_bot.send_message(settings.ADMIN_ID, f"Error handling grade callback: {e}")
