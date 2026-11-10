from aiogram import Router, F, flags
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.enums import ChatAction
from typing import Optional, Sequence

from flashcard.app.audio import AudioUseCases, PreviewPart
from flashcard.app.creation import CardReady, CreationUseCases, GenerateResult, InvalidInput, Saved
from flashcard.app.quota import QuotaExceeded
from flashcard.telegram.helpers.credits import credits_exceeded_text
from flashcard.services.i18n import I18nService
from flashcard.language import LanguageConfig
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.telegram.keyboards import expression_action_kb
from flashcard.telegram.helpers.callback_utils import safe_answer_callback
from flashcard.telegram.ui.factories.audio_callback import SpeechKeyCallback
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


async def _listenable(audio_use_cases: AudioUseCases, result: GenerateResult) -> Sequence[PreviewPart]:
    """A generated card's parts to listen to. Without them the card still arrives, just silent."""
    if not isinstance(result, CardReady):
        return ()
    try:
        return await audio_use_cases.preview_parts(result.card)
    except Exception:
        logger.warning("Could not register the preview's audio", exc_info=True)
        return ()


def _listen_rows(markup: Optional[InlineKeyboardMarkup]) -> Optional[InlineKeyboardMarkup]:
    """The Listen rows of a generated card's buttons, kept once the card is saved."""
    say = f"{SpeechKeyCallback.__prefix__}{SpeechKeyCallback.__separator__}"
    rows = [row for row in (markup.inline_keyboard if markup else [])
            if row and all((button.callback_data or "").startswith(say) for button in row)]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _present(
    i18n: I18nService, result: GenerateResult, language: LanguageConfig, audio_parts: Sequence[PreviewPart] = (),
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Message text and buttons for a generation result."""
    if isinstance(result, InvalidInput):
        text = i18n.get(
            "messages.errors.invalid_learning_language_input",
            language=language.name,
        )
        if result.suggestions:
            text = f"{text}\n" + "\n".join(result.suggestions[:3])
        return text, None
    if isinstance(result, QuotaExceeded):
        return credits_exceeded_text(i18n, result), None
    content = render_expression_card(result.card, learning_flag=language.flag)["content"]
    if isinstance(result, CardReady):
        return content, expression_action_kb(i18n, result.card.norm, audio_parts)
    return content, None


@router.message(F.text & ~F.via_bot & ~F.from_user.is_bot)
@flags.chat_action(ChatAction.TYPING)
async def handle_text_message(
    message: Message, creation_use_cases: CreationUseCases, audio_use_cases: AudioUseCases,
    language: LanguageConfig, i18n: I18nService,
):
    if len(message.text) > 150:
        await message.answer(i18n.get("messages.errors.input_too_long"))
        return

    status_msg = await message.answer(i18n.get("messages.working"))

    async def notify_fallback() -> None:
        await status_msg.edit_text(i18n.get("messages.llm_fallback"))

    result = await creation_use_cases.generate(
        message.from_user.id,
        message.text,
        on_fallback=notify_fallback,
    )
    text, kb = _present(i18n, result, language, await _listenable(audio_use_cases, result))

    await status_msg.edit_text(
        text=text,
        reply_markup=kb
    )


@router.callback_query(F.data.startswith("save:"))
async def handle_save(
    callback: CallbackQuery, creation_use_cases: CreationUseCases, audio_use_cases: AudioUseCases, i18n: I18nService,
):
    # Format: save:{norm}
    norm = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    result = await creation_use_cases.save(user_id, norm)

    if isinstance(result, Saved):
        logger.info(f"Saved to collection received for user {user_id}!")
        try:
            await audio_use_cases.keep_saved_word(norm)
        except Exception:
            logger.warning("Could not keep the saved word's audio", exc_info=True)
        await safe_answer_callback(callback, i18n.get("callbacks.save.success_message"), show_alert=True)
        # Edit message to show saved status
        # Just extra check, could be omitted
        original_text = callback.message.text or callback.message.caption or ""
        await callback.message.edit_text(f"{original_text}{i18n.get('callbacks.save.success_tag', norm=norm)}",
                                         reply_markup=_listen_rows(callback.message.reply_markup))
        
        # Onboarding tip: after first save, nudge about /settings
        if await creation_use_cases.claim_first_save_tip(user_id):
            await callback.message.answer(i18n.get("messages.tips.first_save"))
    else:
        # Duplicate case
        await safe_answer_callback(callback, i18n.get("callbacks.save.already_exists"), show_alert=True)

        # Get the current markup
        current_markup = callback.message.reply_markup

        # Check if markup and buttons exist (safety check)
        if current_markup and current_markup.inline_keyboard:
            # Create a shallow copy of the keyboard rows to avoid modifying the original object directly
            keyboard = [list(row) for row in current_markup.inline_keyboard]
            
            if keyboard and keyboard[0]:
                # Check if the first button is the save button
                if keyboard[0][0].callback_data.startswith("save:"):
                    keyboard[0].pop(0)
                    # If the row is now empty, remove the row itself
                    if not keyboard[0]:
                        keyboard.pop(0)
            
            # Apply the change
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data.startswith("regen:"))
@flags.chat_action(ChatAction.TYPING)
async def handle_regen(
    callback: CallbackQuery, creation_use_cases: CreationUseCases, audio_use_cases: AudioUseCases,
    language: LanguageConfig, i18n: I18nService,
):
    # Kept to restore the card if regenerating fails.
    original_text = callback.message.html_text
    callback_markup = callback.message.reply_markup
    await callback.message.edit_text(i18n.get("callbacks.regen.working"))

    expression = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    async def notify_fallback() -> None:
        await callback.message.edit_text(i18n.get("messages.llm_fallback"))

    async def restore_card() -> None:
        await callback.message.edit_text(text=original_text, reply_markup=callback_markup)

    try:
        result = await creation_use_cases.generate(user_id, expression, on_fallback=notify_fallback)
    except Exception:
        # The error handler tells the user; the card must not stay stuck on "working".
        try:
            await restore_card()
        except Exception:
            logger.warning("Could not restore the card after a failed regenerate", exc_info=True)
        raise

    if isinstance(result, CardReady):
        # New text, so new Listen buttons.
        text, kb = _present(i18n, result, language, await _listenable(audio_use_cases, result))
        await callback.message.edit_text(text=text, reply_markup=kb)
        return

    # Failed: put the card and its buttons back, so the user can still save it or retry.
    await restore_card()
    if isinstance(result, QuotaExceeded):
        # Too long for an alert (200 characters).
        text, _ = _present(i18n, result, language)
        await callback.message.answer(text)
        await safe_answer_callback(callback)
    else:
        await safe_answer_callback(callback, i18n.get("callbacks.regen.failed"), show_alert=True)
