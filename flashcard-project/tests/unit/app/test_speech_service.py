"""SpeechService and SpeechCache: one generation per text, expiry by source, and the expiry migration."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from flashcard.app.quota import QuotaPolicy
from flashcard.app.speech import Clip, SpeechFailed, SpeechService, speakable
from flashcard.services.consumption import ConsumptionService
from flashcard.services.speech_cache import LEGACY_LIFETIME, SpeechCache
from tests.helpers import TEST_LIMITS, make_user
from tests.integration.helpers import InMemoryCollection

USER = 7
DAY = timedelta(days=1)


def _build(synthesize=None):
    provider = SimpleNamespace(synthesize=synthesize or AsyncMock(return_value=b"mp3"))
    entries = InMemoryCollection()
    quota = QuotaPolicy(ConsumptionService(users=InMemoryCollection()), TEST_LIMITS)
    quota.record_audio = AsyncMock()
    users = SimpleNamespace(get_user=AsyncMock(return_value=make_user(user_id=str(USER))))
    service = SpeechService(cache=SpeechCache(entries=entries), provider=provider, quota=quota, user_service=users)
    return service, provider, entries


def _expires(entries, key):
    return next(doc for doc in entries.docs if doc["_id"] == key)["expires_at"]


class TestOneGenerationPerText:

    async def test_two_requests_at_once_generate_and_pay_once(self):
        release = asyncio.Event()

        async def slow(text, voice):
            await release.wait()
            return b"mp3"

        service, _, entries = _build(AsyncMock(side_effect=slow))
        spoken = speakable("Andiamo al mare.", "it", DAY)

        first = asyncio.create_task(service.speak(USER, spoken))
        second = asyncio.create_task(service.speak(USER + 1, spoken))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second)

        assert all(isinstance(r, Clip) and r.audio == b"mp3" for r in results)
        service.provider.synthesize.assert_awaited_once()
        service.quota.record_audio.assert_awaited_once()
        assert len(entries.docs) == 1

    async def test_a_waiter_from_a_longer_source_extends_the_clip(self):
        """A preview (1 day) generates; the saved card's word (60 days) joins it: the clip gets 60 days."""
        release = asyncio.Event()

        async def slow(text, voice):
            await release.wait()
            return b"mp3"

        service, _, entries = _build(AsyncMock(side_effect=slow))
        short, long = speakable("ciao", "it", DAY, word=True), speakable("ciao", "it", 60 * DAY, word=True)

        first = asyncio.create_task(service.speak(USER, short))
        await asyncio.sleep(0)
        second = asyncio.create_task(service.speak(USER, long))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)

        service.provider.synthesize.assert_awaited_once()
        assert _expires(entries, long.key) - datetime.now(timezone.utc) > 59 * DAY

    async def test_a_waiter_hears_of_a_failure_too(self):
        release = asyncio.Event()

        async def failing(text, voice):
            await release.wait()
            raise RuntimeError("403")

        service, _, _ = _build(AsyncMock(side_effect=failing))
        spoken = speakable("Andiamo al mare.", "it", DAY)

        tasks = [asyncio.create_task(service.speak(USER, spoken)) for _ in range(2)]
        await asyncio.sleep(0)
        release.set()

        assert all(isinstance(r, SpeechFailed) for r in await asyncio.gather(*tasks))
        assert not service._in_flight

    async def test_the_first_stored_clip_stays(self):
        service, _, entries = _build()
        key = speakable("ciao", "it", DAY, word=True).key

        await service.cache.put(key, "ciao", "it", b"first", "it-IT-ElsaNeural", DAY)
        await service.cache.put(key, "ciao", "it", b"second", "it-IT-IsabellaNeural", DAY)

        assert len(entries.docs) == 1 and entries.docs[0]["audio"] == b"first"


class TestExpiry:

    async def test_a_play_never_shortens_the_date(self):
        service, _, entries = _build()
        long = speakable("ciao", "it", 60 * DAY, word=True)
        await service.speak(USER, long)
        before = _expires(entries, long.key)

        await service.speak(USER, speakable("ciao", "it", DAY, word=True))

        assert _expires(entries, long.key) == before

    async def test_a_longer_source_moves_it_forward(self):
        service, _, entries = _build()
        await service.speak(USER, speakable("ciao", "it", DAY, word=True))

        clip = await service.speak(USER, speakable("ciao", "it", 60 * DAY, word=True))

        assert _expires(entries, clip.key) - datetime.now(timezone.utc) > 59 * DAY

    async def test_repeated_plays_write_once(self):
        service, _, entries = _build()
        spoken = speakable("ciao", "it", 60 * DAY, word=True)
        await service.speak(USER, spoken)
        entries.update_one = AsyncMock(wraps=entries.update_one)

        await service.speak(USER, spoken)
        await service.speak(USER, spoken)

        entries.update_one.assert_not_awaited()

    async def test_nothing_unspeakable_is_offered(self):
        assert speakable("", "it", DAY) is None
        assert speakable("ciao", "xx", DAY) is None
        assert speakable("parola " * 100, "it", DAY) is None
        assert speakable("  ciao ", "it", DAY).text == "ciao"


class TestMigration:

    async def test_entries_from_before_get_a_date_and_the_old_index_goes(self):
        last_used = datetime(2026, 11, 7, tzinfo=timezone.utc)
        entries = InMemoryCollection([
            {"_id": "old", "audio": b"mp3", "voice": "v", "last_used_at": last_used},
            {"_id": "new", "audio": b"mp3", "expires_at": last_used},
        ])
        await entries.create_index([("last_used_at", 1)], expireAfterSeconds=90 * 86400)
        cache = SpeechCache(entries=entries)

        assert await cache.ensure_indexes() == 1
        assert _expires(entries, "old") == last_used + LEGACY_LIFETIME
        assert _expires(entries, "new") == last_used
        assert entries.indexes == {(("expires_at",), False, False)}

        assert await cache.ensure_indexes() == 0
