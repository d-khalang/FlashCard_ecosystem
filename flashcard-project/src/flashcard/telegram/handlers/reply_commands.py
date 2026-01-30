from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.enums import ChatAction
from aiogram import flags

from flashcard.services.user import UserService
from flashcard.telegram.keyboards import get_reply_settings_keyboard
from flashcard.services.i18n import i18n

router = Router()

@router.message(F.text == i18n.get("messages.buttons.pause_learning"))
@router.message(F.text == i18n.get("messages.buttons.resume_learning"))
async def handle_status_change(message: Message, user_service: UserService):
    """
    Handles the text buttons from the persistent ReplyKeyboard.
    """
    user_id = message.from_user.id
    # Toggle (logic is same for both buttons: flip the bit)
    new_status = await user_service.toggle_active_status(user_id)
    
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
    await message.answer("Settings closed.", reply_markup=ReplyKeyboardRemove())