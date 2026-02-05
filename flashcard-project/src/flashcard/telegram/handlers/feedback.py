from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import ForceReply

from flashcard.telegram.states.feedback import FeedbackStates
from flashcard.services.i18n import i18n
from flashcard.settings import settings

router = Router()

@router.message(Command("feedback"))
async def cmd_feedback(message: types.Message, state: FSMContext):
    """
    Initiates feedback flow.
    """
    await state.set_state(FeedbackStates.waiting_message)
    
    prompt = i18n.get("commands.feedback.prompt")
    placeholder = i18n.get("commands.feedback.placeholder")
    
    await message.answer(
        prompt,
        reply_markup=ForceReply(input_field_placeholder=placeholder, selective=True)
    )

@router.message(FeedbackStates.waiting_message)
async def process_feedback(message: types.Message, state: FSMContext, logger_bot: Bot):
    """
    Process the feedback message.
    """
    # Check for cancellation command explicitly if user typed /cancel
    if message.text and message.text.lower().lstrip().startswith("/can"):
         await state.clear()
         await message.answer(i18n.get("commands.feedback.cancelled"), reply_markup=types.ReplyKeyboardRemove())
         return

    feedback_text = message.text
    user = message.from_user.full_name
    username = message.from_user.username
    user_id = message.from_user.id
    
    admin_msg = (
        f"📩 <b>New Feedback</b>\n"
        f"From: {user} (@{username}) [<code>{user_id}</code>]\n\n"
        f"{feedback_text}"
    )
    
    try:
        await logger_bot.send_message(chat_id=settings.ADMIN_ID, text=admin_msg)
        await message.answer(i18n.get("commands.feedback.success"), reply_markup=types.ReplyKeyboardRemove())
    except Exception as e:
        await message.answer(f"Error sending feedback: {e}")
        
    await state.clear()
