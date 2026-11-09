"""
Listening to a card, for the bot and the Mini App alike.

A clip is asked for by card and part, never by text: what is spoken is always the user's stored
card, so this cannot be used as a general text to speech service. It follows that a preview that was
not saved has no audio. Words come from the cache; every other part is generated each time, and each
client keeps its own replay (the app in memory, the bot's message in the chat). Only generated clips
count against the daily limit.
"""
import asyncio
import re
from dataclasses import dataclass
from typing import Callable, Literal, Optional, Union, get_args

from flashcard.app.quota import QuotaExceeded, QuotaPolicy
from flashcard.app.review import CardNotFound, NotPending, Throttled
from flashcard.language import LanguageConfig
from flashcard.schemas.expression import Expression, TranslationLine
from flashcard.schemas.languages import ALIAS_MAP, LANGUAGE_DATA
from flashcard.schemas.user import UserId
from flashcard.services.audio_cache import AudioWordCache, word_key
from flashcard.services.expression import ExpressionService
from flashcard.services.speech import VOICES, SpeechProvider, random_voice
from flashcard.services.user import UserService
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

CardPart = Literal["word", "definition", "example", "translation_0", "translation_1"]
TRANSLATION_PARTS: tuple[CardPart, ...] = ("translation_0", "translation_1")

# Well within Telegram's 30 s to answer a button.
SPEECH_TIMEOUT_SECONDS = 15.0
# Far above any card's text: a longer one is not worth a request.
MAX_TEXT_CHARS = 600

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
class Clip:
    audio: bytes
    # For a word: lets the bot remember Telegram's id of the file (see `remember_telegram_file`).
    word_key: Optional[str] = None
    telegram_file_id: Optional[str] = None


@dataclass(frozen=True)
class PartMissing:
    """The card has no such part, or nothing can speak it."""


@dataclass(frozen=True)
class SpeechFailed:
    pass


@dataclass(frozen=True)
class ListenablePart:
    part: CardPart
    # The translation's own label; None for the parts every card names the same.
    label: Optional[str] = None


ClipResult = Union[Clip, CardNotFound, PartMissing, QuotaExceeded, SpeechFailed, Throttled]
PartsResult = Union[list[ListenablePart], CardNotFound, NotPending]
GenerationGate = Callable[[], Optional[Throttled]]


class AudioUseCases:
    def __init__(
        self,
        expression_service: ExpressionService,
        user_service: UserService,
        quota: QuotaPolicy,
        word_cache: AudioWordCache,
        speech: SpeechProvider,
        language: LanguageConfig,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.quota = quota
        self.word_cache = word_cache
        self.speech = speech
        self.language = language

    async def parts(self, user_id: UserId, expression_id: str, *, message_id: int) -> PartsResult:
        """What can be listened to on the card in this message, while that message waits for a grade."""
        expression = await self.expressions.get_expression(user_id, expression_id)
        if expression is None:
            return CardNotFound()
        if expression.pending_message_id != message_id:
            return NotPending()
        found: list[ListenablePart] = []
        for part in get_args(CardPart):
            if self._text_and_language(expression, part) is not None:
                found.append(ListenablePart(part, _translation_label(expression, part)))
        return found

    async def clip(
        self, user_id: UserId, expression_id: str, part: CardPart,
        before_generation: Optional[GenerationGate] = None,
    ) -> ClipResult:
        """One part of the user's card as MP3. `before_generation` is asked right before generating."""
        expression = await self.expressions.get_expression(user_id, expression_id)
        if expression is None:
            return CardNotFound()
        spoken = self._text_and_language(expression, part)
        if spoken is None:
            return PartMissing()
        text, language_code = spoken

        key = word_key(language_code, text) if part == "word" else None
        if key is not None:
            cached = await self.word_cache.get(key)
            if cached is not None:
                return Clip(audio=cached.audio, word_key=key, telegram_file_id=cached.telegram_file_id)

        quota = self.quota.check_audio(await self.users.get_user(user_id))
        if isinstance(quota, QuotaExceeded):
            return quota
        if before_generation is not None:
            refused = before_generation()
            if refused is not None:
                return refused

        voice = random_voice(language_code)
        try:
            audio = await asyncio.wait_for(self.speech.synthesize(text, voice), SPEECH_TIMEOUT_SECONDS)
        except Exception as error:
            # The failure rate is what says when to move to a paid provider. The text stays out of logs.
            logger.warning("Speech failed: voice=%s part=%s error=%s", voice, part, type(error).__name__)
            return SpeechFailed()

        logger.info("Speech generated: voice=%s part=%s chars=%d", voice, part, len(text))
        if key is not None:
            await self.word_cache.put(key, audio, voice)
        await self.quota.record_audio(user_id)
        return Clip(audio=audio, word_key=key)

    async def remember_telegram_file(self, key: str, file_id: str) -> None:
        """The bot's id of a word's file, so the next send of that word uploads nothing."""
        await self.word_cache.set_telegram_file_id(key, file_id)

    def _text_and_language(self, expression: Expression, part: str) -> Optional[tuple[str, str]]:
        """What this part says and in which language, or None when there is nothing to say."""
        learning = self.language.code
        if part == "word":
            return _spoken(expression.value, learning)
        card = expression.last_card.card if expression.last_card is not None else None
        if card is None:
            return None
        if part == "definition":
            return _spoken(card.learning_definition, learning)
        if part == "example":
            return _spoken(card.learning_example, learning)
        line = _translation_line(expression, part)
        if line is None:
            return None
        language_code = language_of_label(line.label)
        return _spoken(line.text, language_code) if language_code is not None else None


def _spoken(text: Optional[str], language_code: str) -> Optional[tuple[str, str]]:
    """The one rule for what can be spoken, so the bot never offers a button that cannot work."""
    text = (text or "").strip()
    if not text or len(text) > MAX_TEXT_CHARS or language_code not in VOICES:
        return None
    return text, language_code


def _translation_line(expression: Expression, part: str) -> Optional[TranslationLine]:
    if part not in TRANSLATION_PARTS or expression.last_card is None:
        return None
    lines = expression.last_card.card.translations
    index = TRANSLATION_PARTS.index(part)
    return lines[index] if index < len(lines) else None


def _translation_label(expression: Expression, part: str) -> Optional[str]:
    line = _translation_line(expression, part)
    return line.label if line is not None else None
