from aiogram import Router, Bot, flags
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatAction

from flashcard.settings import settings
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.services.user import UserService
from flashcard.services.consumption import ConsumptionService
from flashcard.services.i18n import i18n
from flashcard.telegram.ui.expression import format_review_message
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.schemas.languages import get_language_flag
from flashcard.schemas.defaults import DEFAULT_LANG_LEVEL, DEFAULT_LANG_1_CODE
from flashcard.utils.logger import get_logger, notify_admin_with_trace

logger = get_logger(__name__)
router = Router()


#TODO: Think about how to adapt last_sent and last_interacted when the last one was revereced
# as we use that for retreival (probably no problem) but first level doc does not give a clue
# about the the last interaction if it was reveresed. semantically wrong. last sent!!!
@router.message(Command("get"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_get(message: Message, expression_service: ExpressionService, llm_service: LLMService, user_service: UserService, consumption_service: ConsumptionService):
    """
    Handle /get command to review a flashcard.
    """
    user_id = message.from_user.id
    
    # 1. Get review candidate
    # Result is now a dict {doc: ..., direction: ...} or None
    result = await expression_service.get_review_candidate(user_id)
    
    if not result:
        # No cards to review
        # Using the message from n8n or similar intent
        await message.answer(i18n.get("commands.get.no_memory"))
        return
        
    candidate = result["doc"]
    direction = result.get("direction", "forward")

    # 2. Get user preferences
    user = await user_service.get_user(user_id)
    
    # 3. Generate content (Definition, Translations, Example)
    # Using user preferences
    card = await llm_service.generate_expression_card(
        raw=candidate['value'],
        level=user.target_level or DEFAULT_LANG_LEVEL,
        lang1_code=user.primary_language or DEFAULT_LANG_1_CODE,
        lang2_code=user.secondary_language,
        lang1_label=get_language_flag(user.primary_language),  
        lang2_label=get_language_flag(user.secondary_language)  
    )

    # 4. Format Message
    # We pass direction to formatter to decide what to show/hide
    text = format_review_message(card, candidate['value'], direction=direction)

    # 5. Keyboard
    keyboard = get_review_keyboard(str(candidate['_id']), direction=direction)
    
    # 6. Send & Update
    sent_msg = await message.answer(text, reply_markup=keyboard)
    
    # Update DB
    await expression_service.update_expression_sent(str(candidate['_id']), sent_msg.message_id)
    await user_service.update_user_last_push(user_id)
    
    # Track consumption
    await consumption_service.increment(user_id, "cards_generated", uses_own_key=user.api_config is not None)


@router.callback_query(GradeCallback.filter())
async def handle_grade(callback: CallbackQuery, callback_data: GradeCallback, expression_service: ExpressionService, user_service: UserService, logger_bot: Bot):
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
            
            # Onboarding tip: after first review, nudge about Dual Mode
            user = await user_service.get_user(user_id)
            if user.onboarding_step == 1:
                await callback.message.answer(i18n.get("messages.tips.first_review"))
                await user_service.advance_onboarding(user_id, 1)
        else:
            await callback.answer(i18n.get("callbacks.grade.error_missing"), show_alert=True)
            
    except ValueError:
        #TODO: Have a consistent schema for logging errors to logger bot
        await callback.answer(i18n.get("callbacks.grade.invalid_data"), show_alert=True)
        await notify_admin_with_trace(logger_bot, f"Invalid callback data: {callback.data}")

    except Exception as e:
        logger.error(f"Error handling grade callback: {e}", exc_info=True)
        await callback.answer(i18n.get("callbacks.grade.error_generic"), show_alert=True)
        await notify_admin_with_trace(logger_bot, f"Error handling grade callback: {e}")
