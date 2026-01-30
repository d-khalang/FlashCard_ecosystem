from aiogram.filters.callback_data import CallbackData
from typing import Optional

class SettingsCallback(CallbackData, prefix="set"):
    action: str # nav, select
    section: str # lang_p, lang_s, level, interval
    value: Optional[str] = None
