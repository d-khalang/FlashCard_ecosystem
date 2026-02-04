from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ChatAction
from aiogram import flags

from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.telegram.keyboards import expression_action_kb
from flashcard.telegram.utils.lang_labels import label_for
from flashcard.telegram.utils.card_generator import generate_and_render_card
from flashcard.services.i18n import i18n
from flashcard.services.user import UserService

router = Router()


@router.message(F.text)
@flags.chat_action(ChatAction.TYPING)
async def handle_text_message(message: Message, llm_service: LLMService, user_service: UserService):
    status_msg = await message.answer(i18n.get("messages.working"))

    text, success, card = await generate_and_render_card(llm_service, user_service, message.from_user.id, message.text)
    
    kb = expression_action_kb(card.norm) if success else None
    
    await status_msg.edit_text(
        text=text,
        reply_markup=kb
    )
   
