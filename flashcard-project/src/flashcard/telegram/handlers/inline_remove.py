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

from flashcard.services.expression import ExpressionService
from flashcard.services.i18n import i18n
from flashcard.telegram.helpers.callback_utils import safe_answer_callback, safe_call
from flashcard.telegram.ui.factories.inline_remove_callback import InlineRemoveCallback
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()

_MIN_INLINE_QUERY_LENGTH = 2
_INLINE_RESULT_LIMIT = 50


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
    expression_service: ExpressionService,
):
    query = (inline_query.query or "").strip()
    if len(query) < _MIN_INLINE_QUERY_LENGTH:
        await inline_query.answer(results=[], cache_time=1, is_personal=True)
        return

    expressions = await expression_service.search_expressions(
        inline_query.from_user.id,
        query,
        limit=_INLINE_RESULT_LIMIT,
    )

    results: list[InlineQueryResultArticle] = []
    for expression in expressions:
        expression_id = str(expression.get("_id", ""))
        value = expression.get("value")

        if not expression_id or not value:
            logger.warning(f"Skipping malformed inline remove expression: {expression}")
            continue

        results.append(
            InlineQueryResultArticle(
                id=expression_id,
                title=value,
                description=i18n.get("callbacks.inline_remove.result_description"),
                input_message_content=InputTextMessageContent(message_text=value),
                reply_markup=_build_initial_remove_markup(expression_id),
            )
        )

    await inline_query.answer(results=results, cache_time=2, is_personal=True)


@router.callback_query(InlineRemoveCallback.filter())
async def handle_inline_remove_callback(
    callback: CallbackQuery,
    callback_data: InlineRemoveCallback,
    expression_service: ExpressionService,
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
            removed = await expression_service.remove_expression(
                callback.from_user.id,
                expression_id,
            )
            await _edit_inline_reply_markup(callback, reply_markup=None)

            if removed:
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
