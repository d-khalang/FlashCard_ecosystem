from aiogram.fsm.state import State, StatesGroup

class FeedbackStates(StatesGroup):
    waiting_message = State()
