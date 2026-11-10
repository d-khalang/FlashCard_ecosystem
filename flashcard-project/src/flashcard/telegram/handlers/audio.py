"""
Listening to cards. A part arrives as a voice message replying to the card; the message stays in the
chat, so replaying it costs nothing here.

Review card: 🔊 opens a row of the card's parts. Grading removes the keyboard, so a card can be
listened to only until it is graded.
Generated card (preview): its parts' buttons are there from the start and play by speech key.
"""
import time
from typing import Awaitable, Callable, Optional, get_args

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyParameters

from flashcard.app.audio import AudioUseCases, CardPart, Clip
from flashcard.app.speech import UnknownKey
from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardNotFound, NotPending
from flashcard.schemas.user import UserId
from flashcard.services.i18n import I18nService
from flashcard.telegram.helpers.callback_utils import clear_buttons, safe_answer_callback
from flashcard.telegram.keyboards import get_review_keyboard
from flashcard.telegram.ui.factories.audio_callback import AUDIO_MENU, AudioCallback, SpeechKeyCallback
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()

# A second tap this soon gets a hint instead of a new clip: the first one is right there in the chat.
REPEAT_WINDOW_SECONDS = 60.0
FILE_NAME = "kartino.mp3"
VOICE_FORBIDDEN = "voice_messages_forbidden"
NOT_MODIFIED = "message is not modified"


class _RecentTaps:
    """Parts sent (or being sent) to a user in the last moments, in memory: a restart just forgets them."""

    def __init__(self, window: float = REPEAT_WINDOW_SECONDS) -> None:
        self.window = window
        self._times: dict[tuple, float] = {}

    def claim(self, key: tuple) -> bool:
        """True if this tap should send; False if the same one was just sent."""
        now = time.monotonic()
        self._times = {k: t for k, t in self._times.items() if now - t < self.window}
        if key in self._times:
            return False
        self._times[key] = now
        return True

    def release(self, key: tuple) -> None:
        """A tap that sent nothing can be tried again at once."""
        self._times.pop(key, None)


_recent = _RecentTaps()


@router.callback_query(AudioCallback.filter())
async def handle_audio(
    callback: CallbackQuery, callback_data: AudioCallback, audio_use_cases: AudioUseCases, bot: Bot, i18n: I18nService,
):
    if callback_data.part == AUDIO_MENU:
        await _open_parts(callback, callback_data, audio_use_cases, bot, i18n)
    elif callback_data.part in get_args(CardPart):
        await _send_part(callback, callback_data, audio_use_cases, bot, i18n)
    else:
        await safe_answer_callback(callback, i18n.get("callbacks.audio.unavailable"), show_alert=True)


async def _open_parts(
    callback: CallbackQuery, data: AudioCallback, audio_use_cases: AudioUseCases, bot: Bot, i18n: I18nService,
) -> None:
    parts = await audio_use_cases.parts(
        callback.from_user.id, data.expression_id, message_id=callback.message.message_id)
    if isinstance(parts, CardNotFound):
        await safe_answer_callback(callback, i18n.get("callbacks.grade.error_missing"), show_alert=True)
        await clear_buttons(callback, bot)
        return
    if isinstance(parts, NotPending):
        # Opening the row would put the grade buttons back on a card they no longer work for.
        await safe_answer_callback(callback, i18n.get("callbacks.grade.not_pending"))
        await clear_buttons(callback, bot)
        return
    direction = "reverse" if data.direction == "rev" else "forward"
    try:
        # Through the bot: on a card too old for Telegram to send back, the message has no edit methods.
        await bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id, message_id=callback.message.message_id,
            reply_markup=get_review_keyboard(i18n, data.expression_id, direction=direction, audio_parts=parts))
    except TelegramBadRequest as error:
        # A double tap: the first one already opened the row.
        if NOT_MODIFIED not in str(error).lower():
            logger.warning("Could not open the audio buttons for user %s: %s", callback.from_user.id, error)
            await safe_answer_callback(callback, i18n.get("callbacks.audio.unavailable"), show_alert=True)
            return
    await safe_answer_callback(callback)


async def _send_part(
    callback: CallbackQuery, data: AudioCallback, audio_use_cases: AudioUseCases, bot: Bot, i18n: I18nService,
) -> None:
    await _send(callback, data.expression_id, data.part, audio_use_cases, bot, i18n,
                lambda: audio_use_cases.clip(callback.from_user.id, data.expression_id, data.part))


@router.callback_query(SpeechKeyCallback.filter())
async def handle_speech_key(
    callback: CallbackQuery, callback_data: SpeechKeyCallback, audio_use_cases: AudioUseCases, bot: Bot,
    i18n: I18nService,
):
    """A part of a generated card, by the key its button carries."""
    key = callback_data.key
    if not key:
        await safe_answer_callback(callback, i18n.get("callbacks.audio.unavailable"), show_alert=True)
        return
    await _send(callback, key, "", audio_use_cases, bot, i18n,
                lambda: audio_use_cases.preview_clip(callback.from_user.id, key))


async def _send(
    callback: CallbackQuery, source: str, part: str, audio_use_cases: AudioUseCases, bot: Bot, i18n: I18nService,
    fetch: Callable[[], Awaitable],
) -> None:
    user_id: UserId = callback.from_user.id
    tap = (user_id, source, part)
    if not _recent.claim(tap):
        await safe_answer_callback(callback, i18n.get("callbacks.audio.already_sent"))
        return

    problem: Optional[str] = None
    try:
        result = await fetch()
        if isinstance(result, Clip):
            await _deliver(callback.message, result, audio_use_cases, bot)
        elif isinstance(result, QuotaExceeded):
            problem = i18n.get("callbacks.audio.limit", limit=result.limit)
        elif isinstance(result, CardNotFound):
            problem = i18n.get("callbacks.grade.error_missing")
        elif isinstance(result, UnknownKey):
            problem = i18n.get("callbacks.audio.expired")
        else:
            problem = i18n.get("callbacks.audio.unavailable")
    except Exception:
        logger.warning("Could not send audio to user %s", user_id, exc_info=True)
        problem = i18n.get("callbacks.audio.unavailable")

    if problem is not None:
        _recent.release(tap)
        await safe_answer_callback(callback, problem, show_alert=True)
    else:
        await safe_answer_callback(callback)


async def _deliver(card_message: Message, clip: Clip, audio_use_cases: AudioUseCases, bot: Bot) -> None:
    """As a voice message; as an audio file for a user whose privacy settings refuse voice messages."""
    target = dict(
        chat_id=card_message.chat.id,
        reply_parameters=ReplyParameters(message_id=card_message.message_id, allow_sending_without_reply=True),
    )
    upload = BufferedInputFile(clip.audio, filename=FILE_NAME)
    try:
        sent = await _send_voice(bot, clip, upload, target)
    except TelegramBadRequest as error:
        if VOICE_FORBIDDEN not in str(error).lower():
            raise
        await bot.send_audio(audio=upload, **target)
        return
    if sent.voice is not None and sent.voice.file_id != clip.telegram_file_id:
        await audio_use_cases.remember_telegram_file(clip.key, sent.voice.file_id)


async def _send_voice(bot: Bot, clip: Clip, upload: BufferedInputFile, target: dict) -> Message:
    """By the stored file id when there is one. Another bot's id never works, so then upload after all."""
    if clip.telegram_file_id is not None:
        try:
            return await bot.send_voice(voice=clip.telegram_file_id, **target)
        except TelegramBadRequest as error:
            if VOICE_FORBIDDEN in str(error).lower():
                raise
            logger.warning("Stored Telegram file refused, uploading again: %s", error)
    return await bot.send_voice(voice=upload, **target)
