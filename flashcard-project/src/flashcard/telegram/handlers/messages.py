from aiogram import Router, F
import logging
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

from flashcard.telegram.keyboards import get_explanation_keyboard, get_reply_keyboard

router = Router()

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
async def handle_text_message(message: Message):
    # Minimal placeholder logic
    text = f"Explanation for: {message.text}"
    await message.answer(
        text=text,
        reply_markup=get_explanation_keyboard()
    )
    await message.answer(
        text="this is a reply keyboard",
        reply_markup=get_reply_keyboard()
    )
