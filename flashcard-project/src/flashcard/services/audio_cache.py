"""
Stored audio of words, the one card part whose text repeats. Definitions, examples and translations
are written anew by the LLM, so they are generated on demand and never stored (the disk is limited).

The collection holds only what can be generated again: backups leave it out, and a clip unused for
EXPIRE_AFTER_SECONDS is removed by Mongo. One clip per word, in the voice picked when it was first
generated, so several voices never mean several copies.
"""
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from flashcard.utils.time import now_utc

EXPIRE_AFTER_SECONDS = int(timedelta(days=90).total_seconds())
# Refreshing the expiry on every play would be a write per tap; a day is precise enough for 90 days.
TOUCH_AFTER = timedelta(days=1)


def word_key(language_code: str, text: str) -> str:
    """The same for any casing or spacing of a word, which all sound the same."""
    normalized = " ".join(text.split()).casefold()
    return hashlib.sha256(f"{language_code}\n{normalized}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedWord:
    audio: bytes
    # Only ever set by this language's bot, which is the only bot using this database.
    telegram_file_id: Optional[str]


class AudioWordCache:
    def __init__(self, words):
        """`words`: the audio_words collection."""
        self.words = words

    async def get(self, key: str) -> Optional[CachedWord]:
        doc = await self.words.find_one({"_id": key})
        if doc is None:
            return None
        now = now_utc()
        if now - doc["last_used_at"] > TOUCH_AFTER:
            await self.words.update_one({"_id": key}, {"$set": {"last_used_at": now}})
        return CachedWord(audio=bytes(doc["audio"]), telegram_file_id=doc.get("telegram_file_id"))

    async def put(self, key: str, audio: bytes, voice: str) -> None:
        """Keep the first clip when two requests generate the same word at once."""
        now = now_utc()
        await self.words.update_one(
            {"_id": key},
            {"$setOnInsert": {"audio": audio, "voice": voice, "created_at": now, "last_used_at": now}},
            upsert=True,
        )

    async def set_telegram_file_id(self, key: str, file_id: str) -> None:
        await self.words.update_one({"_id": key}, {"$set": {"telegram_file_id": file_id}})

    async def ensure_indexes(self) -> None:
        await self.words.create_index([("last_used_at", 1)], expireAfterSeconds=EXPIRE_AFTER_SECONDS)
