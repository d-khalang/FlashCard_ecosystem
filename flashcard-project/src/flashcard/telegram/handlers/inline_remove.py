from __future__ import annotations

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from flashcard.app.collection import CollectionUseCases, Matches, QueryTooShort, Removed
from flashcard.services.i18n import i18n
from flashcard.telegram.helpers.callback_utils import safe_answer_callback, safe_call
from flashcard.telegram.ui.factories.inline_remove_callback import InlineRemoveCallback
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


def _build_initial_remove_markup(expression_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get("messages.buttons.inline_remove"),
                    callback_data=InlineRemoveCallback(
                        action="prompt",
                        expression_id=expression_id,
                    ).pack(),
                )
            ]
        ]
    )


def _build_confirmation_markup(expression_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get("messages.buttons.inline_remove_cancel"),
                    callback_data=InlineRemoveCallback(
                        action="cancel",
                        expression_id=expression_id,
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=i18n.get("messages.buttons.inline_remove_confirm"),
                    callback_data=InlineRemoveCallback(
                        action="confirm",
                        expression_id=expression_id,
                    ).pack(),
                ),
            ]
        ]
    )


async def _edit_inline_reply_markup(
    callback: CallbackQuery,
    *,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    if callback.inline_message_id:
        await callback.bot.edit_message_reply_markup(
            inline_message_id=callback.inline_message_id,
            reply_markup=reply_markup,
        )
        return

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=reply_markup)
        return

    logger.warning("Inline remove callback has neither inline_message_id nor callback.message.")


@router.inline_query()
async def handle_inline_remove_query(
    inline_query: InlineQuery,
    collection_use_cases: CollectionUseCases,
):
    result = await collection_use_cases.search(inline_query.from_user.id, inline_query.query or "")
    if not isinstance(result, Matches):
        cache_time = 1 if isinstance(result, QueryTooShort) else 2
        await inline_query.answer(results=[], cache_time=cache_time, is_personal=True)
        return

    results = [
        InlineQueryResultArticle(
            id=item.id,
            title=item.value,
            description=i18n.get("callbacks.inline_remove.result_description"),
            input_message_content=InputTextMessageContent(message_text=item.value),
            reply_markup=_build_initial_remove_markup(item.id),
        )
        for item in result.items
    ]
    await inline_query.answer(results=results, cache_time=2, is_personal=True)


@router.callback_query(InlineRemoveCallback.filter())
async def handle_inline_remove_callback(
    callback: CallbackQuery,
    callback_data: InlineRemoveCallback,
    collection_use_cases: CollectionUseCases,
):
    expression_id = callback_data.expression_id

    try:
        if callback_data.action == "prompt":
            await _edit_inline_reply_markup(
                callback,
                reply_markup=_build_confirmation_markup(expression_id),
            )
            await safe_answer_callback(
                callback,
                i18n.get("callbacks.inline_remove.prompt"),
                show_alert=True,
            )
            return

        if callback_data.action == "cancel":
            await _edit_inline_reply_markup(
                callback,
                reply_markup=_build_initial_remove_markup(expression_id),
            )
            await safe_answer_callback(
                callback,
                i18n.get("callbacks.inline_remove.cancelled"),
            )
            return

        if callback_data.action == "confirm":
            result = await collection_use_cases.remove(callback.from_user.id, expression_id)
            await _edit_inline_reply_markup(callback, reply_markup=None)

            if isinstance(result, Removed):
                await safe_answer_callback(
                    callback,
                    i18n.get("callbacks.inline_remove.removed"),
                )
            else:
                await safe_answer_callback(
                    callback,
                    i18n.get("callbacks.inline_remove.missing"),
                    show_alert=True,
                )
            return

        logger.warning(f"Unknown inline remove callback action received: {callback_data.action}")
        await safe_answer_callback(
            callback,
            i18n.get("callbacks.inline_remove.invalid"),
            show_alert=True,
        )
    except TelegramBadRequest as exc:
        logger.warning(f"TelegramBadRequest while handling inline remove callback: {exc}")
        await safe_call(
            safe_answer_callback(
                callback,
                i18n.get("callbacks.inline_remove.invalid"),
                show_alert=True,
            )
        )
    except Exception as exc:
        logger.error(f"Error handling inline remove callback: {exc}", exc_info=True)
        await safe_call(
            safe_answer_callback(
                callback,
                i18n.get("callbacks.inline_remove.error"),
                show_alert=True,
            )
        )
