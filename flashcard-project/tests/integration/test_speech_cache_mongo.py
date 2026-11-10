"""SpeechCache on real MongoDB: what the in-memory fake can only imitate (upsert collisions, TTL index options)."""
from datetime import datetime, timedelta, timezone

from flashcard.services.speech_cache import LEGACY_INDEX_NAME, LEGACY_LIFETIME, SpeechCache

DAY = timedelta(days=1)


async def test_the_first_clip_stays_and_the_date_only_grows(mongo_cols):
    cache = SpeechCache(entries=mongo_cols["audio_words"])
    await cache.register("k", "ciao", "it", DAY)

    await cache.put("k", "ciao", "it", b"first", "it-IT-ElsaNeural", 60 * DAY)
    await cache.put("k", "ciao", "it", b"second", "it-IT-IsabellaNeural", DAY)

    doc = await mongo_cols["audio_words"].find_one({"_id": "k"})
    assert bytes(doc["audio"]) == b"first" and doc["voice"] == "it-IT-ElsaNeural"
    assert doc["text"] == "ciao" and doc["language"] == "it"
    assert doc["expires_at"] - datetime.now(timezone.utc) > 59 * DAY


async def test_migration_dates_old_entries_and_swaps_the_index(mongo_cols):
    entries = mongo_cols["audio_words"]
    last_used = datetime(2026, 11, 7, tzinfo=timezone.utc)
    await entries.insert_one({"_id": "old", "audio": b"mp3", "voice": "v", "last_used_at": last_used})
    await entries.create_index([("last_used_at", 1)], expireAfterSeconds=90 * 86400)
    cache = SpeechCache(entries=entries)

    assert await cache.ensure_indexes() == 1
    assert await cache.ensure_indexes() == 0

    doc = await entries.find_one({"_id": "old"})
    assert doc["expires_at"] == last_used + LEGACY_LIFETIME
    indexes = await entries.index_information()
    assert LEGACY_INDEX_NAME not in indexes
    assert indexes["expires_at_1"]["expireAfterSeconds"] == 0
