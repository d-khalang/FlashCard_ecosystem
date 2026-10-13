from typing import Optional

from aiogram import F, Router, Bot, flags
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatAction
from contextlib import suppress
from aiogram.exceptions import TelegramBadRequest

from flashcard.app.verb import Found, InvalidVerb, NoVerb, VerbUseCases
from flashcard.telegram.ui.verb import format_verb_conjugation, format_verb_message
from flashcard.telegram.ui.factories.verb_callback import VerbCallback
from flashcard.services.i18n import i18n
from flashcard.telegram.keyboards import get_verb_keyboard
from flashcard.telegram.helpers.callback_utils import safe_answer_callback
from flashcard.utils.logger import get_logger, notify_admin_with_trace

logger = get_logger(__name__)
router = Router()


@router.message(Command("verb"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_verb(message: Message, command: CommandObject, verb_use_cases: VerbUseCases, logger_bot: Bot):
    """
    Handle /verb command.
    """
    # "Searching..." is replaced by the result or the error.
    status_msg: Optional[Message] = None

    async def notify_searching(verb: str) -> None:
        nonlocal status_msg
        status_msg = await message.answer(i18n.get("commands.verb.searching", verb=verb))

    async def show(text: str, reply_markup=None) -> None:
        if status_msg is None:
            await message.answer(text, reply_markup=reply_markup)
        else:
            await status_msg.edit_text(text=text, reply_markup=reply_markup)

    # aiogram strips the command and any @botname; args is None when empty or whitespace.
    try:
        result = await verb_use_cases.lookup(message.from_user.id, command.args, on_searching=notify_searching)
    except Exception as e:
        logger.error(f"Verb data retrieval error for '{command.args}': {e}")
        await notify_admin_with_trace(
            logger_bot, f"Verb data error for '{command.args}' (user {message.from_user.id}): {str(e)}")
        await show(i18n.get("commands.verb.api_error"))
        return

    if isinstance(result, Found):
        await show(format_verb_message(result.data), reply_markup=get_verb_keyboard(result.data))
    elif isinstance(result, NoVerb):
        await show(i18n.get("commands.verb.instruction"))
    elif isinstance(result, InvalidVerb):
        logger.warning(f"Invalid verb: {result.verb}")
        await show(i18n.get("commands.verb.invalid"))
    else:
        await show(i18n.get("commands.verb.api_error"))


@router.callback_query(VerbCallback.filter())
async def handle_conjugation(callback: CallbackQuery, callback_data: VerbCallback, verb_use_cases: VerbUseCases):
    """
    Handle verb conjugation navigation callbacks.
    """
    result = await verb_use_cases.conjugation(callback_data.verb)
    if not isinstance(result, Found):
        await safe_answer_callback(callback, i18n.get("callbacks.verb.not_found"), show_alert=True)
        return

    html_text = format_verb_conjugation(result.data, callback_data.mood, callback_data.tense)

    # Pressing the shown tense again leaves the text unchanged, which Telegram rejects.
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text=html_text, reply_markup=callback.message.reply_markup)
    await safe_answer_callback(callback, i18n.get("callbacks.verb.updated"))


@router.callback_query(F.data.startswith("noop|"))
async def handle_header_button(callback: CallbackQuery):
    """Section headers in the verb keyboard are labels; just stop the spinner."""
    await safe_answer_callback(callback)
