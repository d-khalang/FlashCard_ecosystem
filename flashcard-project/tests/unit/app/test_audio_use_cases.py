"""AudioUseCases (the card source) on a real SpeechService, with the provider faked and the cache on the in-memory Mongo fake."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from flashcard.app.audio import AudioUseCases, PartMissing, language_of_label
from flashcard.app.quota import QuotaExceeded, QuotaPolicy
from flashcard.app.review import CardNotFound, NotPending, Throttled
from flashcard.app.speech import (
    CARD_TEXT_LIFETIME, PREVIEW_LIFETIME, WORD_LIFETIME, Clip, SpeechFailed, SpeechService, UnknownKey,
)
from flashcard.schemas.expression import CardSettings, Expression, ExpressionCard, StoredCard, TranslationLine
from flashcard.schemas.user import UserConsumption, UserTier
from flashcard.services.consumption import ConsumptionService
from flashcard.services.speech import VOICES, random_voice
from flashcard.services.speech_cache import SpeechCache, speech_key
from tests.helpers import TEST_LANGUAGE, TEST_LIMITS, make_user
from tests.integration.helpers import InMemoryCollection

USER = 7
MESSAGE_ID = 99
EXPRESSION_ID = str(ObjectId())
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def _card(value="il mare") -> ExpressionCard:
    return ExpressionCard(
        success=True, norm=value, learning_definition="Grande distesa d'acqua.",
        translations=[TranslationLine(label="🇮🇷 FA", text="دریا"), TranslationLine(label="🏴 XX", text="sea")],
        learning_example="Andiamo al mare.", note=None, suggestions=[],
    )


def _expression(value="il mare", card=True) -> Expression:
    stored = StoredCard(card=_card(value), settings=CardSettings(level="A2", primary_language="fa"),
                        generated_at=NOW) if card else None
    return Expression(_id=EXPRESSION_ID, user_id=str(USER), value=value, created_at=NOW, last_card=stored,
                      pending_message_id=MESSAGE_ID)


def _build(*, expression=None, user=None):
    provider = SimpleNamespace(synthesize=AsyncMock(return_value=b"mp3"))
    entries = InMemoryCollection()
    users = SimpleNamespace(get_user=AsyncMock(return_value=user or make_user(user_id=str(USER))))
    quota = QuotaPolicy(ConsumptionService(users=InMemoryCollection()), TEST_LIMITS)
    quota.record_audio = AsyncMock()
    uses = AudioUseCases(
        expression_service=SimpleNamespace(get_expression=AsyncMock(return_value=expression)),
        speech=SpeechService(cache=SpeechCache(entries=entries), provider=provider, quota=quota, user_service=users),
        language=TEST_LANGUAGE,
    )
    return uses, provider, entries


def _used_up(tier=UserTier.normal, **fields):
    today = datetime.now(timezone.utc).date().isoformat()
    return make_user(user_id=str(USER), tier=tier, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                     consumption=UserConsumption(consumption_date=today, audio_generated=3), **fields)


def _lifetime_left(entries, key) -> timedelta:
    doc = next(doc for doc in entries.docs if doc["_id"] == key)
    return doc["expires_at"] - datetime.now(timezone.utc)


def _close(left: timedelta, lifetime: timedelta) -> bool:
    return abs(left - lifetime) < timedelta(minutes=1)


class TestWords:

    async def test_the_first_play_generates_and_stores_with_one_voice(self):
        uses, provider, entries = _build(expression=_expression())

        result = await uses.clip(USER, EXPRESSION_ID, "word")

        assert isinstance(result, Clip) and result.audio == b"mp3"
        text, voice = provider.synthesize.await_args.args
        assert text == "il mare" and voice in VOICES["it"]
        assert len(entries.docs) == 1 and entries.docs[0]["voice"] == voice
        assert entries.docs[0]["_id"] == speech_key("it", "il mare", fold_case=True)
        uses.speech.quota.record_audio.assert_awaited_once()

    async def test_the_next_play_reuses_it_free_of_charge(self):
        uses, provider, entries = _build(expression=_expression())
        await uses.clip(USER, EXPRESSION_ID, "word")

        again = await uses.clip(USER, EXPRESSION_ID, "word")

        assert again.audio == b"mp3"
        provider.synthesize.assert_awaited_once()
        uses.speech.quota.record_audio.assert_awaited_once()
        assert len(entries.docs) == 1

    async def test_casing_and_spacing_share_a_word_but_not_a_sentence(self):
        assert speech_key("it", "Il  Mare ", fold_case=True) == speech_key("it", "il mare", fold_case=True)
        assert speech_key("it", "il mare", fold_case=True) != speech_key("en", "il mare", fold_case=True)
        assert speech_key("it", "Va  bene.", fold_case=False) == speech_key("it", "Va bene.", fold_case=False)
        assert speech_key("it", "Va bene.", fold_case=False) != speech_key("it", "va bene.", fold_case=False)

    async def test_a_stored_word_plays_even_when_the_daily_limit_is_used_up(self):
        uses, _, _ = _build(expression=_expression())
        await uses.clip(USER, EXPRESSION_ID, "word")
        uses.speech.users.get_user.return_value = _used_up()

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), Clip)

    async def test_a_word_without_a_generated_card_can_still_be_heard(self):
        uses, _, _ = _build(expression=_expression(card=False))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), Clip)

    async def test_the_telegram_file_id_comes_back_with_the_clip(self):
        uses, _, _ = _build(expression=_expression())
        first = await uses.clip(USER, EXPRESSION_ID, "word")

        await uses.remember_telegram_file(first.key, "file-1")

        assert (await uses.clip(USER, EXPRESSION_ID, "word")).telegram_file_id == "file-1"

    async def test_a_word_lives_for_the_word_lifetime(self):
        uses, _, entries = _build(expression=_expression())

        clip = await uses.clip(USER, EXPRESSION_ID, "word")

        assert _close(_lifetime_left(entries, clip.key), WORD_LIFETIME)


class TestOtherParts:

    @pytest.mark.parametrize("part, text", [("definition", "Grande distesa d'acqua."), ("example", "Andiamo al mare.")])
    async def test_are_stored_for_a_short_while(self, part, text):
        uses, provider, entries = _build(expression=_expression())

        first = await uses.clip(USER, EXPRESSION_ID, part)
        await uses.clip(USER, EXPRESSION_ID, part)

        assert provider.synthesize.await_count == 1
        assert provider.synthesize.await_args.args[0] == text
        uses.speech.quota.record_audio.assert_awaited_once()
        assert _close(_lifetime_left(entries, first.key), CARD_TEXT_LIFETIME)

    async def test_a_translation_speaks_in_its_own_language(self):
        uses, provider, _ = _build(expression=_expression())

        await uses.clip(USER, EXPRESSION_ID, "translation_0")

        text, voice = provider.synthesize.await_args.args
        assert text == "دریا" and voice in VOICES["fa"]

    async def test_a_translation_in_an_unknown_language_is_missing(self):
        uses, provider, _ = _build(expression=_expression())

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "translation_1"), PartMissing)
        provider.synthesize.assert_not_awaited()

    async def test_no_stored_card_means_no_such_part(self):
        uses, _, _ = _build(expression=_expression(card=False))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "definition"), PartMissing)


class TestRefusals:

    async def test_someone_elses_or_a_removed_card_is_not_found(self):
        uses, provider, _ = _build(expression=None)

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), CardNotFound)
        provider.synthesize.assert_not_awaited()

    async def test_the_daily_limit_stops_generating(self):
        uses, provider, _ = _build(expression=_expression(), user=_used_up())

        result = await uses.clip(USER, EXPRESSION_ID, "example")

        assert isinstance(result, QuotaExceeded) and result.limit == 3
        provider.synthesize.assert_not_awaited()

    async def test_an_own_llm_key_does_not_lift_the_limit(self):
        uses, _, _ = _build(expression=_expression(),
                            user=_used_up(api_config={"provider": "groq", "api_key": "k", "model": "m"}))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "example"), QuotaExceeded)

    async def test_an_admin_has_no_limit(self):
        uses, _, _ = _build(expression=_expression(), user=_used_up(tier=UserTier.admin))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "example"), Clip)

    async def test_the_gate_can_refuse_right_before_generating(self):
        uses, provider, _ = _build(expression=_expression())
        refused = Throttled(retry_after=5)

        assert await uses.clip(USER, EXPRESSION_ID, "example", before_generation=lambda: refused) is refused
        provider.synthesize.assert_not_awaited()

    async def test_a_failing_service_costs_nothing_and_stores_nothing(self):
        uses, provider, entries = _build(expression=_expression())
        provider.synthesize.side_effect = RuntimeError("403")

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), SpeechFailed)
        uses.speech.quota.record_audio.assert_not_awaited()
        assert entries.docs == []


class TestParts:

    async def test_lists_only_what_can_be_spoken(self):
        uses, _, _ = _build(expression=_expression())

        parts = await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID)

        assert [(p.part, p.label) for p in parts] == [
            ("word", None), ("definition", None), ("example", None), ("translation_0", "🇮🇷 FA")]

    @pytest.mark.parametrize("part", ["definition", "example"])
    async def test_never_offers_what_the_clip_would_refuse(self, part):
        expression = _expression()
        too_long = "parola " * 100
        expression.last_card.card.learning_definition = too_long
        expression.last_card.card.learning_example = too_long
        uses, provider, _ = _build(expression=expression)

        assert part not in [p.part for p in await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID)]
        assert isinstance(await uses.clip(USER, EXPRESSION_ID, part), PartMissing)
        provider.synthesize.assert_not_awaited()

    async def test_a_card_that_is_gone_is_not_found(self):
        uses, _, _ = _build(expression=None)

        assert await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID) == CardNotFound()

    async def test_a_message_no_longer_waiting_for_a_grade_is_not_pending(self):
        uses, _, _ = _build(expression=_expression())

        assert await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID + 1) == NotPending()


class TestPreview:

    async def test_registers_each_part_without_generating(self):
        uses, provider, entries = _build()

        parts = await uses.preview_parts(_card())

        assert [(p.part, p.label) for p in parts] == [
            ("word", None), ("definition", None), ("example", None), ("translation_0", "🇮🇷 FA")]
        provider.synthesize.assert_not_awaited()
        assert {doc["_id"] for doc in entries.docs} == {p.key for p in parts}
        assert all("audio" not in doc and _close(_lifetime_left(entries, doc["_id"]), PREVIEW_LIFETIME)
                   for doc in entries.docs)

    async def test_a_part_plays_by_its_key(self):
        uses, provider, _ = _build()
        example = next(p for p in await uses.preview_parts(_card()) if p.part == "example")

        clip = await uses.preview_clip(USER, example.key)

        assert isinstance(clip, Clip) and clip.key == example.key
        assert provider.synthesize.await_args.args[0] == "Andiamo al mare."
        uses.speech.quota.record_audio.assert_awaited_once()

    async def test_an_unknown_or_expired_key_plays_nothing(self):
        uses, provider, _ = _build()

        assert isinstance(await uses.preview_clip(USER, "0" * 64), UnknownKey)
        provider.synthesize.assert_not_awaited()

    async def test_the_preview_word_is_the_saved_cards_word(self):
        """Heard in the preview, then on the saved card: one clip, and it now lives as long as a word."""
        uses, provider, entries = _build(expression=_expression("Il mare"))
        word = (await uses.preview_parts(_card("il mare")))[0]
        await uses.preview_clip(USER, word.key)

        clip = await uses.clip(USER, EXPRESSION_ID, "word")

        assert clip.key == word.key
        provider.synthesize.assert_awaited_once()
        assert _close(_lifetime_left(entries, word.key), WORD_LIFETIME)

    async def test_a_word_stored_before_text_was_kept_plays_from_a_preview(self):
        """Entries from before this change have audio but no text: the preview reuses them, and fills the text in."""
        uses, provider, entries = _build()
        key = speech_key("it", "il mare", fold_case=True)
        await entries.insert_one({"_id": key, "audio": b"old", "voice": "v",
                                  "expires_at": datetime.now(timezone.utc) + WORD_LIFETIME})

        word = (await uses.preview_parts(_card()))[0]
        clip = await uses.preview_clip(USER, word.key)

        assert word.key == key and isinstance(clip, Clip) and clip.audio == b"old"
        provider.synthesize.assert_not_awaited()
        assert entries.docs[0]["text"] == "il mare" and entries.docs[0]["language"] == "it"

    async def test_saving_the_word_gives_its_preview_clip_a_words_life(self):
        uses, _, entries = _build()
        word = (await uses.preview_parts(_card()))[0]
        await uses.preview_clip(USER, word.key)

        await uses.keep_saved_word("Il  Mare")

        assert _close(_lifetime_left(entries, word.key), WORD_LIFETIME)

    async def test_saving_a_word_never_heard_stores_nothing(self):
        uses, _, entries = _build()

        await uses.keep_saved_word("il mare")

        assert entries.docs == []

    async def test_a_preview_never_shortens_a_word(self):
        uses, _, entries = _build(expression=_expression())
        clip = await uses.clip(USER, EXPRESSION_ID, "word")

        await uses.preview_parts(_card())
        await uses.preview_clip(USER, clip.key)

        assert _close(_lifetime_left(entries, clip.key), WORD_LIFETIME)


class TestLanguages:

    @pytest.mark.parametrize("label, code", [
        ("🇮🇷 FA", "fa"), ("🇬🇧", "en"), ("EN", "en"), ("Persian", "fa"), ("🏴 XX", None), ("", None),
        ("🇮🇷FA", "fa"), ("🇮🇷 (FA)", "fa"), ("(FA)", "fa"), ("🇺🇸 EN", "en"),
    ])
    def test_of_a_label(self, label, code):
        assert language_of_label(label) == code

    def test_every_language_of_the_app_has_a_voice(self):
        from flashcard.schemas.languages import LANGUAGE_DATA

        assert set(VOICES) == set(LANGUAGE_DATA)
        assert all(random_voice(code) for code in LANGUAGE_DATA)

    def test_no_voice_guesses_the_language(self):
        assert not [voice for voices in VOICES.values() for voice in voices if "Multilingual" in voice]
