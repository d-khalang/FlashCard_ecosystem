from aiogram import Router, F
from aiogram.types import CallbackQuery


router = Router()

@router.callback_query(F.data.startswith("save:"))
async def handle_save(callback: CallbackQuery, cols):
    # Placeholder save
    await cols["expression"].insert_one({
        "user_id": callback.from_user.id,
        "original_text": "Placeholder",
        "card_id": "Placeholder"
    })
    print("Saved to collection received!")
    await callback.answer("Saved to collection!", show_alert=False)
    await callback.message.edit_text(f"{callback.message.text}\n\n(Saved)")

@router.callback_query(F.data.startswith("regen:"))
async def handle_regen(callback: CallbackQuery):
    # Placeholder regeneration logic
    new_text = "Regenerated Explanation..."
    from flashcard.telegram.keyboards import get_explanation_keyboard
    await callback.message.edit_text(
        text=new_text,
        reply_markup=get_explanation_keyboard()
    )
    await callback.answer("Regenerated!")
