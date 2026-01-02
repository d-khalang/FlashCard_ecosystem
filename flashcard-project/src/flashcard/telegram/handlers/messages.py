from aiogram import Router, F
from aiogram.types import Message
from flashcard.telegram.keyboards import get_explanation_keyboard

router = Router()

@router.message(F.text)
async def handle_text_message(message: Message):
    # Minimal placeholder logic
    text = f"Explanation for: {message.text}"
    await message.answer(
        text=text,
        reply_markup=get_explanation_keyboard()
    )
