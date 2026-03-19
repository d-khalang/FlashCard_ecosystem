from typing import Literal

from aiogram.filters.callback_data import CallbackData


class InlineRemoveCallback(CallbackData, prefix="inline_remove"):
    action: Literal["prompt", "confirm", "cancel"]
    expression_id: str
