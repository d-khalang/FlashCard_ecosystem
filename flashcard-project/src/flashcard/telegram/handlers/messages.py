from aiogram import Router, F
import logging
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
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

@router.message(F.text)
@flags.chat_action(ChatAction.TYPING)
async def handle_text_message(message: Message):
    status_msg = await message.answer("Working on it...")

    # TODO later: load from DB by user_id/chat_id
    level = DEFAULT_LEVEL
    langs = DEFAULT_LANGS  # must be 2 items

    lang1_code = langs[0]
    lang2_code = langs[1] if len(langs) > 1 else ""
    lang1_label = label_for(lang1_code)
    lang2_label = label_for(lang2_code) if lang2_code else ""

    llm = LLMService()
    card = await llm.generate_expression_card(
        raw=message.text,
        level=level,
        lang1_code=lang1_code,
        lang2_code=lang2_code,
        lang1_label=lang1_label,
        lang2_label=lang2_label,
    )

    text = render_expression_card(card)
    kb = expression_action_kb(card.norm)
    
    await status_msg.edit_text(
        text=text,
        reply_markup=kb
    )
   
