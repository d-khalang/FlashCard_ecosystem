from aiogram.filters.callback_data import CallbackData

# Structured callback schema
# format: conj|mood|tense|verb
class VerbCallback(CallbackData, prefix="conj", sep="|"):
    mood: str
    tense: str
    verb: str