"""
Listening to cards, for the bot and the Mini App alike: the card source of flashcard.app.speech.

A saved card is asked for by card and part, and its text is read from the user's stored card. A
preview (generated, not saved) has no id yet, so its parts are registered when it is shown and asked
for by key. Either way the client never sends the text.
"""
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Optional, Union

from flashcard.app.quota import QuotaExceeded
from flashcard.app.review import CardNotFound, NotPending, Throttled
from flashcard.app.speech import (
    CARD_TEXT_LIFETIME, PREVIEW_LIFETIME, WORD_LIFETIME, Clip, GenerationGate, SpeechFailed, SpeechService,
    Speakable, UnknownKey, speakable,
)
from flashcard.language import LanguageConfig
from flashcard.schemas.expression import ExpressionCard, TranslationLine
from flashcard.schemas.languages import ALIAS_MAP, LANGUAGE_DATA
from flashcard.schemas.user import UserId
from flashcard.services.expression import ExpressionService

CardPart = Literal["word", "definition", "example", "translation_0", "translation_1"]
TRANSLATION_PARTS: tuple[CardPart, ...] = ("translation_0", "translation_1")

_LANGUAGE_BY_FLAG = {data["flag"]: code for code, data in LANGUAGE_DATA.items()}
_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
_WORD = re.compile(r"[^\W\d_]+")


def language_of_label(label: str) -> Optional[str]:
    """The language of a translation label such as "🇮🇷 FA", from its flag or else its words."""
    label = label or ""
    for flag in _FLAG.findall(label):
        if flag in _LANGUAGE_BY_FLAG:
            return _LANGUAGE_BY_FLAG[flag]
    for word in _WORD.findall(label):
        if word.lower() in ALIAS_MAP:
            return ALIAS_MAP[word.lower()]
    return None


@dataclass(frozen=True)
class PartMissing:
    """The card has no such part, or nothing can speak it."""


@dataclass(frozen=True)
class ListenablePart:
    part: CardPart
    # The translation's own label; None for the parts every card names the same.
    label: Optional[str] = None


@dataclass(frozen=True)
class PreviewPart(ListenablePart):
    # What the client sends to play this part.
    key: str = ""


ClipResult = Union[Clip, CardNotFound, PartMissing, QuotaExceeded, SpeechFailed, Throttled]
KeyClipResult = Union[Clip, UnknownKey, QuotaExceeded, SpeechFailed, Throttled]
PartsResult = Union[list[ListenablePart], CardNotFound, NotPending]


class AudioUseCases:
    def __init__(self, expression_service: ExpressionService, speech: SpeechService, language: LanguageConfig):
        self.expressions = expression_service
        self.speech = speech
        self.language = language

    async def parts(self, user_id: UserId, expression_id: str, *, message_id: int) -> PartsResult:
        """What can be listened to on the card in this message, while that message waits for a grade."""
        expression = await self.expressions.get_expression(user_id, expression_id)
        if expression is None:
            return CardNotFound()
        if expression.pending_message_id != message_id:
            return NotPending()
        card = expression.last_card.card if expression.last_card is not None else None
        return [ListenablePart(part, _translation_label(card, part))
                for part, _ in self._speakables(expression.value, card, WORD_LIFETIME, CARD_TEXT_LIFETIME)]

    async def clip(
        self, user_id: UserId, expression_id: str, part: CardPart,
        before_generation: Optional[GenerationGate] = None,
    ) -> ClipResult:
        """One part of the user's saved card as MP3. `before_generation` is asked right before generating."""
        expression = await self.expressions.get_expression(user_id, expression_id)
        if expression is None:
            return CardNotFound()
        card = expression.last_card.card if expression.last_card is not None else None
        found = dict(self._speakables(expression.value, card, WORD_LIFETIME, CARD_TEXT_LIFETIME)).get(part)
        if found is None:
            return PartMissing()
        return await self.speech.speak(user_id, found, before_generation)

    async def preview_parts(self, card: ExpressionCard) -> list[PreviewPart]:
        """Register what can be listened to on a generated card, for play by key until it expires."""
        found = []
        for part, spoken in self._speakables(card.norm, card, PREVIEW_LIFETIME, PREVIEW_LIFETIME):
            key = await self.speech.register(spoken)
            found.append(PreviewPart(part=part, label=_translation_label(card, part), key=key))
        return found

    async def preview_clip(
        self, user_id: UserId, key: str, before_generation: Optional[GenerationGate] = None,
    ) -> KeyClipResult:
        """A part of a preview, by the key `preview_parts` gave it."""
        return await self.speech.speak_key(user_id, key, PREVIEW_LIFETIME, before_generation)

    async def keep_saved_word(self, word: str) -> None:
        """
        A saved word's clip (heard in its preview) now lives as long as a word. Only the word: a saved
        card's other parts are written anew at review, so the preview's clips of them are not its card's.
        """
        found = speakable(word, self.language.code, WORD_LIFETIME, word=True)
        if found is not None:
            await self.speech.keep(found)

    async def remember_telegram_file(self, key: str, file_id: str) -> None:
        await self.speech.remember_telegram_file(key, file_id)

    def _speakables(
        self, word: str, card: Optional[ExpressionCard], word_lifetime: timedelta, text_lifetime: timedelta,
    ) -> list[tuple[CardPart, Speakable]]:
        """Each part that can be spoken, in order."""
        learning = self.language.code
        candidates: list[tuple[CardPart, Optional[Speakable]]] = [
            ("word", speakable(word, learning, word_lifetime, word=True))]
        if card is not None:
            candidates.append(("definition", speakable(card.learning_definition, learning, text_lifetime)))
            candidates.append(("example", speakable(card.learning_example, learning, text_lifetime)))
            for part in TRANSLATION_PARTS:
                line = _translation_line(card, part)
                if line is not None:
                    candidates.append((part, speakable(line.text, language_of_label(line.label), text_lifetime)))
        return [(part, found) for part, found in candidates if found is not None]


def _translation_line(card: Optional[ExpressionCard], part: str) -> Optional[TranslationLine]:
    if part not in TRANSLATION_PARTS or card is None:
        return None
    index = TRANSLATION_PARTS.index(part)
    return card.translations[index] if index < len(card.translations) else None


def _translation_label(card: Optional[ExpressionCard], part: str) -> Optional[str]:
    line = _translation_line(card, part)
    return line.label if line is not None else None

