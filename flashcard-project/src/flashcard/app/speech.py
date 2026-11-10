"""
Speech for every feature: text in, a cached MP3 out, with the daily limit, the cache and its
lifetimes, and the provider behind one door.

Clients never send text. A feature turns its own content into a `Speakable` (cards do it in
flashcard.app.audio), either playing it at once or registering it and giving the client its key.
A key exists only for text the server wrote, so this is never a general text to speech service.

Lifetimes by source (see flashcard.services.speech_cache):
    word 60 days, card text 2 days, preview 1 day. Later: story 3 days, game 1 day.

Only generated clips count against the daily limit; a cached one is free.
"""
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Optional, Union

from flashcard.app.quota import QuotaExceeded, QuotaPolicy
from flashcard.app.review import Throttled
from flashcard.schemas.user import UserId
from flashcard.services.speech import VOICES, SpeechProvider, random_voice
from flashcard.services.speech_cache import SpeechCache, speech_key
from flashcard.services.user import UserService
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

WORD_LIFETIME = timedelta(days=60)
CARD_TEXT_LIFETIME = timedelta(days=2)
PREVIEW_LIFETIME = timedelta(days=1)

# Well within Telegram's 30 s to answer a button.
SPEECH_TIMEOUT_SECONDS = 15.0
# Far above any card's text: a longer one is not worth a request.
MAX_TEXT_CHARS = 600


@dataclass(frozen=True)
class Speakable:
    text: str
    language: str
    lifetime: timedelta
    # A word: any casing is one entry.
    word: bool = False

    @property
    def key(self) -> str:
        return speech_key(self.language, self.text, fold_case=self.word)


def speakable(text: Optional[str], language: Optional[str], lifetime: timedelta, *, word: bool = False) -> Optional[Speakable]:
    """The one rule for what can be spoken, so no client offers a button that cannot work."""
    text = (text or "").strip()
    if not text or len(text) > MAX_TEXT_CHARS or language not in VOICES:
        return None
    return Speakable(text=text, language=language, lifetime=lifetime, word=word)


@dataclass(frozen=True)
class Clip:
    audio: bytes
    # Lets the bot remember Telegram's id of the file (see `remember_telegram_file`).
    key: str
    telegram_file_id: Optional[str] = None


@dataclass(frozen=True)
class UnknownKey:
    """No text was registered under this key, or it has expired."""


@dataclass(frozen=True)
class SpeechFailed:
    pass


GenerationGate = Callable[[], Optional[Throttled]]
SpeakResult = Union[Clip, QuotaExceeded, SpeechFailed, Throttled]


class SpeechService:
    def __init__(self, cache: SpeechCache, provider: SpeechProvider, quota: QuotaPolicy, user_service: UserService):
        self.cache = cache
        self.provider = provider
        self.quota = quota
        self.users = user_service
        # Generations running in this process, by key: a second request for the same text waits for
        # the first instead of generating (and paying) again.
        self._in_flight: dict[str, asyncio.Future] = {}

    async def register(self, speakable_: Speakable) -> str:
        """Keep the text so the client can play it by key later; returns the key."""
        key = speakable_.key
        await self.cache.register(key, speakable_.text, speakable_.language, speakable_.lifetime)
        return key

    async def speak(
        self, user_id: UserId, speakable_: Speakable, before_generation: Optional[GenerationGate] = None,
    ) -> SpeakResult:
        """The clip, from the cache or generated. `before_generation` is asked right before generating."""
        key = speakable_.key
        cached = await self.cache.get(key)
        if cached is not None and cached.audio is not None:
            await self.cache.touch(key, cached, speakable_.lifetime)
            return Clip(audio=cached.audio, key=key, telegram_file_id=cached.telegram_file_id)
        return await self._generate(user_id, key, speakable_, before_generation)

    async def speak_key(
        self, user_id: UserId, key: str, lifetime: timedelta, before_generation: Optional[GenerationGate] = None,
    ) -> Union[SpeakResult, UnknownKey]:
        """A registered text by its key; `lifetime` is that of the source the client asks from."""
        cached = await self.cache.get(key)
        if cached is None:
            return UnknownKey()
        # Before the text check: a clip stored before text was kept has audio but no text.
        if cached.audio is not None:
            await self.cache.touch(key, cached, lifetime)
            return Clip(audio=cached.audio, key=key, telegram_file_id=cached.telegram_file_id)
        if cached.text is None or cached.language not in VOICES:
            return UnknownKey()
        stored = Speakable(text=cached.text, language=cached.language, lifetime=lifetime)
        return await self._generate(user_id, key, stored, before_generation)

    async def keep(self, speakable_: Speakable) -> None:
        """Give stored speech at least this source's lifetime; nothing is stored if there is none yet."""
        await self.cache.extend(speakable_.key, speakable_.lifetime)

    async def remember_telegram_file(self, key: str, file_id: str) -> None:
        """The bot's id of a clip's file, so the next send of it uploads nothing."""
        await self.cache.set_telegram_file_id(key, file_id)

    async def _generate(
        self, user_id: UserId, key: str, speakable_: Speakable, before_generation: Optional[GenerationGate],
    ) -> SpeakResult:
        if key in self._in_flight:
            # Someone else is paying for this clip already.
            return await self._join(key, speakable_.lifetime)

        quota = self.quota.check_audio(await self.users.get_user(user_id))
        if isinstance(quota, QuotaExceeded):
            return quota
        if before_generation is not None:
            refused = before_generation()
            if refused is not None:
                return refused

        # Checked again: the awaits above let another request start the same clip.
        if key in self._in_flight:
            return await self._join(key, speakable_.lifetime)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        audio: Optional[bytes] = None
        try:
            generated = await self._synthesize(self.provider, speakable_)
            if generated is not None:
                audio, voice = generated
                await self.cache.put(key, speakable_.text, speakable_.language, audio, voice, speakable_.lifetime)
                await self.quota.record_audio(user_id)
        finally:
            del self._in_flight[key]
            future.set_result(audio)
        return Clip(audio=audio, key=key) if audio is not None else SpeechFailed()

    async def _join(self, key: str, lifetime: timedelta) -> SpeakResult:
        audio = await asyncio.shield(self._in_flight[key])
        if audio is None:
            return SpeechFailed()
        # The first request stored the clip with its own lifetime; this source may need a longer one.
        await self.cache.extend(key, lifetime)
        return Clip(audio=audio, key=key)

    @staticmethod
    async def _synthesize(provider: SpeechProvider, speakable_: Speakable) -> Optional[tuple[bytes, str]]:
        """The clip and its voice, or None when the provider failed."""
        voice = random_voice(speakable_.language)
        try:
            audio = await asyncio.wait_for(provider.synthesize(speakable_.text, voice), SPEECH_TIMEOUT_SECONDS)
        except Exception as error:
            # The failure rate is what says when to move to a paid provider. The text stays out of logs.
            logger.warning("Speech failed: voice=%s error=%s", voice, type(error).__name__)
            return None
        logger.info("Speech generated: voice=%s chars=%d", voice, len(speakable_.text))
        return audio, voice
