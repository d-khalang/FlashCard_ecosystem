from typing import Literal

from aiogram.filters.callback_data import CallbackData

# `part` is a card part (flashcard.app.audio.CardPart), or this to open the row of parts.
AUDIO_MENU = "menu"


class AudioCallback(CallbackData, prefix="audio"):
    expression_id: str
    part: str
    # Only to rebuild the card's grade buttons when the row of parts opens.
    direction: Literal["fwd", "rev"]
