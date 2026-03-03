from aiogram import Router, F, flags
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.enums import ChatAction

from flashcard.services.llm.llm import LLMService
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from flashcard.services.consumption import ConsumptionService
from flashcard.services.i18n import i18n
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.telegram.keyboards import expression_action_kb
from flashcard.telegram.helpers.card_generator import generate_and_render_card
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()

# TODO: block the suspicious messages or at least very long ones
@router.message(F.text)
@flags.chat_action(ChatAction.TYPING)
async def handle_text_message(message: Message, llm_service: LLMService, user_service: UserService, consumption_service: ConsumptionService):
    if len(message.text) > 150:
        await message.answer(i18n.get("messages.errors.input_too_long"))
        return

    status_msg = await message.answer(i18n.get("messages.working"))

    text, success, card, user = await generate_and_render_card(llm_service, user_service, message.from_user.id, message.text)
    
    if success:
        await consumption_service.increment(message.from_user.id, "cards_generated", uses_own_key=user.api_config is not None)
    
    kb = expression_action_kb(card.norm) if success else None
    
    await status_msg.edit_text(
        text=text,
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("save:"))
async def handle_save(callback: CallbackQuery, expression_service: ExpressionService, user_service: UserService):
    # Format: save:{norm}
    norm = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    
    # Attempt to add expression via service
    saved = await expression_service.add_expression(user_id, norm)

    if saved:
        logger.info(f"Saved to collection received for user {user_id}!")
        await callback.answer(i18n.get("callbacks.save.success_message"), show_alert=True)
        # Edit message to show saved status
        # Just extra check, could be omitted
        original_text = callback.message.text or callback.message.caption or ""
        await callback.message.edit_text(f"{original_text}{i18n.get('callbacks.save.success_tag', norm=norm)}")
        
        # Onboarding tip: after first save, nudge about /settings
        user = await user_service.get_user(user_id)
        if user.onboarding_step == 0:
            await callback.message.answer(i18n.get("messages.tips.first_save"))
            await user_service.advance_onboarding(user_id, 0)
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
async def handle_regen(callback: CallbackQuery, llm_service: LLMService, user_service: UserService, consumption_service: ConsumptionService):
    callback_markup = callback.message.reply_markup
    await callback.message.edit_text(i18n.get("callbacks.regen.working"))

    expression = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    text, success, card, user = await generate_and_render_card(llm_service, user_service, user_id, expression)

    if success:
        await consumption_service.increment(user_id, "cards_generated", uses_own_key=user.api_config is not None)
        await callback.message.edit_text(
            text=text,
            reply_markup=callback_markup
        )
    else:
        await callback.message.edit_text(i18n.get("callbacks.regen.failed"))
