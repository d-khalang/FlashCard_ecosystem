import base64
from typing import Literal

from aiogram.filters.callback_data import CallbackData

# `part` is a card part (flashcard.app.audio.CardPart), or this to open the row of parts.
AUDIO_MENU = "menu"


class AudioCallback(CallbackData, prefix="audio"):
    expression_id: str
    part: str
    # Only to rebuild the card's grade buttons when the row of parts opens.
    direction: Literal["fwd", "rev"]


class SpeechKeyCallback(CallbackData, prefix="say"):
    """
    A registered text by its speech key (a card preview's part). The hex key is 64 characters, too
    many for Telegram's 64-byte button data, so it travels as 43 characters of base64url.
    """
    k: str

    @classmethod
    def for_key(cls, key: str) -> "SpeechKeyCallback":
        return cls(k=base64.urlsafe_b64encode(bytes.fromhex(key)).rstrip(b"=").decode("ascii"))

    @property
    def key(self) -> str:
        """The hex key; empty for data that does not decode to one."""
        try:
            raw = base64.urlsafe_b64decode(self.k + "=" * (-len(self.k) % 4))
        except ValueError:
            return ""
        return raw.hex() if len(raw) == 32 else ""
