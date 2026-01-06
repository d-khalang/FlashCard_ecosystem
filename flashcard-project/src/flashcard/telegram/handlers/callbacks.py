from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress

from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.telegram.ui.verb import format_verb_conjugation
from flashcard.services.verb import VerbService

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
        await callback.answer("Verb data not found.", show_alert=True)
        return

    # 2. Format specific view
    html_text = format_verb_conjugation(verb_data, mood, tense)
    
    # 3. Edit message    
    # 'suppress' handles the crash if the user clicks the same button twice (content doesn't change)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(
            text=html_text,
            # Pass the same keyboard back if you want the buttons to stay
            reply_markup=callback.message.reply_markup, 
            parse_mode="HTML"
        )
        
        await callback.answer("👇🏻 Conjugation updated")
