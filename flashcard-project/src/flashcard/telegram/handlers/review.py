from aiogram import Router, Bot, flags
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatAction

import asyncio

from flashcard.app.review import CardNotFound, NoCandidate, QuotaExceeded, ReviewUseCases
from flashcard.language import LanguageConfig
from flashcard.services.i18n import I18nService
from flashcard.telegram.ui.expression import format_review_message
from flashcard.telegram.ui.review_label import review_label
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.telegram.helpers.callback_utils import safe_answer_callback, safe_call
from flashcard.utils.logger import get_logger, notify_admin_with_trace

logger = get_logger(__name__)
router = Router()


@router.message(Command("get"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_get(message: Message, review_use_cases: ReviewUseCases, language: LanguageConfig, i18n: I18nService):
    """
    Handle /get command to review a flashcard.
    """
    user_id = message.from_user.id
    result = await review_use_cases.prepare_next(user_id)

    if isinstance(result, NoCandidate):
        await message.answer(i18n.get("commands.get.no_memory"))
        return

    if isinstance(result, QuotaExceeded):
        await message.answer(i18n.get(
            "messages.errors.quota_exceeded",
            type="card",
            tier=result.tier,
            limit=result.limit,
        ))
        return

    text = format_review_message(
        result.card, result.value, direction=result.direction, learning_flag=language.flag,
        label=review_label(i18n, result))
    keyboard = get_review_keyboard(i18n, result.expression_id, direction=result.direction)
    sent_msg = await message.answer(text, reply_markup=keyboard)
    await review_use_cases.mark_sent(user_id, result, sent_msg.message_id)


@router.callback_query(GradeCallback.filter())
async def handle_grade(callback: CallbackQuery, callback_data: GradeCallback, review_use_cases: ReviewUseCases, logger_bot: Bot, admin_id: int, i18n: I18nService):
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
        
        result = await review_use_cases.grade(user_id, expression_id, grade, direction)

        if isinstance(result, CardNotFound):
            await safe_answer_callback(callback, i18n.get("callbacks.grade.error_missing"), show_alert=True)
            return

        await callback.message.edit_text(f"{callback.message.text}{i18n.get('callbacks.grade.rated', grade=grade)}")
        await safe_answer_callback(callback, i18n.get("callbacks.grade.success"))

        # Onboarding tip: after first review, nudge about Dual Mode
        if await review_use_cases.claim_first_review_tip(user_id):
            await callback.message.answer(i18n.get("messages.tips.first_review"))
        
    except ValueError:
        #TODO: Have a consistent schema for logging errors to logger bot
        await safe_call(safe_answer_callback(callback, i18n.get("callbacks.grade.invalid_data"), show_alert=True))
        await safe_call(notify_admin_with_trace(logger_bot, f"Invalid callback data: {callback.data}", admin_id=admin_id))

    except Exception as e:
        logger.error(f"Error handling grade callback: {e}", exc_info=True)
        await safe_call(safe_answer_callback(callback, i18n.get("callbacks.grade.error_generic"), show_alert=True))
        await safe_call(notify_admin_with_trace(logger_bot, f"Error handling grade callback: {e}", admin_id=admin_id))
