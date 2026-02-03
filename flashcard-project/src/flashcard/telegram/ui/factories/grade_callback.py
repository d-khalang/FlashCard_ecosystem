from aiogram.filters.callback_data import CallbackData
from typing import Literal

class GradeCallback(CallbackData, prefix="grade"):
    expression_id: str
    grade: int
    direction: Literal["fwd", "rev"]