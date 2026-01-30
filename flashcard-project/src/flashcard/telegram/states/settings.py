from aiogram.fsm.state import State, StatesGroup

class SettingsPrompts(StatesGroup):
    waiting_primary_lang = State()
    waiting_secondary_lang = State()
    waiting_target_level = State()
