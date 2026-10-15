from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.enums import ChatAction
from aiogram import flags

from flashcard.app.settings import SettingsUseCases
from flashcard.telegram.keyboards import get_reply_settings_keyboard
from flashcard.services.i18n import i18n

router = Router()

@router.message(F.text == i18n.get("messages.buttons.pause_learning"))
@router.message(F.text == i18n.get("messages.buttons.resume_learning"))
async def handle_status_change(message: Message, settings_use_cases: SettingsUseCases):
    """
    Handles the Pause/Resume text buttons from the persistent ReplyKeyboard.
    The button says what the user wants, so a repeated or stale tap changes nothing.
    """
    resume = message.text == i18n.get("messages.buttons.resume_learning")
    new_status = await settings_use_cases.set_active(message.from_user.id, resume)
    
    # Send feedback + NEW keyboard (with opposite option)
    action_key = "messages.notifications.resumed" if new_status else "messages.notifications.paused"
    feedback_text = i18n.get(action_key)
    
    # We send a message with the new keyboard
    keyboard = get_reply_settings_keyboard(new_status)
    await message.answer(feedback_text, reply_markup=keyboard)


@router.message(F.text == i18n.get("messages.buttons.close_settings"))
async def handle_close_settings(message: Message):
    """
    Removes the reply keyboard.
    """
    await message.answer(i18n.get("commands.settings.closed"), reply_markup=ReplyKeyboardRemove())