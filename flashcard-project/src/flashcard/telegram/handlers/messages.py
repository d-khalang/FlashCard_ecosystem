from aiogram import Router, F
import logging
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ChatAction
from aiogram import flags

from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.telegram.keyboards import expression_action_kb
from flashcard.telegram.utils.lang_labels import label_for

router = Router()

# Temporary defaults (until per-user config in Mongo retrieved)
DEFAULT_LEVEL = "B1"
DEFAULT_LANGS = ["en", "fa"]

logging.basicConfig(level=logging.INFO)

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("help message")
    await message.reply("help reply")

# @router.message(F.text)
# async def handle_text(message: Message):
#     # Minimal placeholder logic
#     text = f"Explanation for: {message.text}"
    # print(message)

from flashcard.telegram.utils.card_generator import generate_and_render_card

@router.message(F.text)
@flags.chat_action(ChatAction.TYPING)
async def handle_text_message(message: Message, llm_service: LLMService):
    status_msg = await message.answer("Working on it...")

    text, success, card = await generate_and_render_card(llm_service, message.text)
    
    kb = expression_action_kb(card.norm) if success else None
    
    await status_msg.edit_text(
        text=text,
        reply_markup=kb
    )
   
