"""
Stored speech, keyed by what is said: the same text in the same language is one entry, whichever
feature asked for it (a card, a preview, later a story or a game).

An entry may hold only its text, registered so that a client can ask for it by key without ever
sending text (see flashcard.app.speech), and gains its audio on the first play.

Each entry has one `expires_at`, and Mongo removes it when that passes. Every source has its own
lifetime; a registration or a play moves the date to `now + lifetime` when that is later, never
earlier. So a word heard now and then stays, a preview played once is soon gone, and text shared by
two sources lives as long as the longer one.

The collection keeps its first name, `audio_words`, from when it held words only. It is still in
the backups (mongodump cannot leave one collection out); the short lifetimes keep it small.
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

from flashcard.utils.time import now_utc

# Before expiry dates, entries were removed 90 days after their last use, by an index on this field.
LEGACY_EXPIRY_FIELD = "last_used_at"
LEGACY_INDEX_NAME = "last_used_at_1"
# Lifetime given to entries stored before expiry dates: they were all words.
LEGACY_LIFETIME = timedelta(days=60)
# Moving the date on every play would be a write per tap; a move shorter than this is skipped.
MAX_TOUCH_STEP = timedelta(days=1)


def speech_key(language_code: str, text: str, *, fold_case: bool) -> str:
    """
    Spacing never changes how text sounds. Case is folded for words only, so any spelling of a word
    is one entry; a sentence keeps its case.
    """
    normalized = " ".join(text.split())
    if fold_case:
        normalized = normalized.casefold()
    return hashlib.sha256(f"{language_code}\n{normalized}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedSpeech:
    # Missing on entries stored before text was kept.
    text: Optional[str]
    language: Optional[str]
    # None until the first play generates it.
    audio: Optional[bytes]
    # Only ever set by this language's bot, which is the only bot using this database.
    telegram_file_id: Optional[str]
    expires_at: Optional[datetime]


def _touch_step(lifetime: timedelta) -> timedelta:
    return min(MAX_TOUCH_STEP, lifetime / 4)


class SpeechCache:
    def __init__(self, entries):
        """`entries`: the audio_words collection."""
        self.entries = entries

    async def get(self, key: str) -> Optional[CachedSpeech]:
        doc = await self.entries.find_one({"_id": key})
        if doc is None:
            return None
        audio = doc.get("audio")
        return CachedSpeech(
            text=doc.get("text"), language=doc.get("language"),
            audio=bytes(audio) if audio is not None else None,
            telegram_file_id=doc.get("telegram_file_id"), expires_at=doc.get("expires_at"),
        )

    async def register(self, key: str, text: str, language: str, lifetime: timedelta) -> None:
        """
        Keep the text, so that the key alone can be played later. Set, not only on insert: an entry
        stored before text was kept gains it here. The key fixes what is said, so this changes nothing else.
        """
        await self.entries.update_one(
            {"_id": key},
            {"$set": {"text": text, "language": language},
             "$setOnInsert": {"created_at": now_utc()},
             "$max": {"expires_at": now_utc() + lifetime}},
            upsert=True,
        )

    async def put(self, key: str, text: str, language: str, audio: bytes, voice: str, lifetime: timedelta) -> None:
        """Keep the first clip when two requests generate the same text at once."""
        expires_at = now_utc() + lifetime
        try:
            await self.entries.update_one(
                {"_id": key, "audio": {"$exists": False}},
                {"$set": {"audio": audio, "voice": voice, "text": text, "language": language},
                 "$setOnInsert": {"created_at": now_utc()},
                 "$max": {"expires_at": expires_at}},
                upsert=True,
            )
        except DuplicateKeyError:
            # Another request stored its clip first; that one stays.
            await self.entries.update_one(
                {"_id": key}, {"$set": {"text": text, "language": language}, "$max": {"expires_at": expires_at}})

    async def touch(self, key: str, cached: CachedSpeech, lifetime: timedelta) -> None:
        """A play: move the expiry to `now + lifetime` when that is meaningfully later."""
        if cached.expires_at is not None and now_utc() + lifetime - cached.expires_at < _touch_step(lifetime):
            return
        await self.extend(key, lifetime)

    async def extend(self, key: str, lifetime: timedelta) -> None:
        """Move the expiry to `now + lifetime` if that is later."""
        await self.entries.update_one({"_id": key}, {"$max": {"expires_at": now_utc() + lifetime}})

    async def set_telegram_file_id(self, key: str, file_id: str) -> None:
        await self.entries.update_one({"_id": key}, {"$set": {"telegram_file_id": file_id}})

    async def ensure_indexes(self) -> int:
        """
        The expiry index, after giving entries from before it a date (last use + LEGACY_LIFETIME);
        then the old index on last use goes. Returns how many entries got a date. Idempotent.
        """
        backfilled = 0
        async for doc in self.entries.find({"expires_at": {"$exists": False}}, {LEGACY_EXPIRY_FIELD: 1}):
            last_used = doc.get(LEGACY_EXPIRY_FIELD) or now_utc()
            await self.entries.update_one(
                {"_id": doc["_id"]}, {"$set": {"expires_at": last_used + LEGACY_LIFETIME}})
            backfilled += 1
        await self.entries.create_index([("expires_at", 1)], expireAfterSeconds=0)
        if LEGACY_INDEX_NAME in await self.entries.index_information():
            await self.entries.drop_index(LEGACY_INDEX_NAME)
        return backfilled

