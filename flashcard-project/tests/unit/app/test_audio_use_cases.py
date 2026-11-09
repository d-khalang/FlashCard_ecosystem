"""AudioUseCases with the speech service faked and the word cache on the in-memory Mongo fake."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from flashcard.app.audio import AudioUseCases, Clip, PartMissing, SpeechFailed, language_of_label
from flashcard.app.quota import QuotaExceeded, QuotaPolicy
from flashcard.app.review import CardNotFound, NotPending, Throttled
from flashcard.schemas.expression import CardSettings, Expression, ExpressionCard, StoredCard, TranslationLine
from flashcard.schemas.user import UserConsumption, UserTier
from flashcard.services.audio_cache import AudioWordCache, word_key
from flashcard.services.consumption import ConsumptionService
from flashcard.services.speech import VOICES, random_voice
from tests.helpers import TEST_LANGUAGE, TEST_LIMITS, make_user
from tests.integration.helpers import InMemoryCollection

USER = 7
MESSAGE_ID = 99
EXPRESSION_ID = str(ObjectId())
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def _expression(value="il mare", card=True) -> Expression:
    stored = StoredCard(
        card=ExpressionCard(
            success=True, norm=value, learning_definition="Grande distesa d'acqua.",
            translations=[TranslationLine(label="🇮🇷 FA", text="دریا"), TranslationLine(label="🏴 XX", text="sea")],
            learning_example="Andiamo al mare.", note=None, suggestions=[],
        ),
        settings=CardSettings(level="A2", primary_language="fa"),
        generated_at=NOW,
    ) if card else None
    return Expression(_id=EXPRESSION_ID, user_id=str(USER), value=value, created_at=NOW, last_card=stored,
                      pending_message_id=MESSAGE_ID)


def _build(*, expression=None, user=None):
    speech = SimpleNamespace(synthesize=AsyncMock(return_value=b"mp3"))
    words = InMemoryCollection()
    users = InMemoryCollection()
    uses = AudioUseCases(
        expression_service=SimpleNamespace(get_expression=AsyncMock(return_value=expression)),
        user_service=SimpleNamespace(get_user=AsyncMock(return_value=user or make_user(user_id=str(USER)))),
        quota=QuotaPolicy(ConsumptionService(users=users), TEST_LIMITS),
        word_cache=AudioWordCache(words=words),
        speech=speech,
        language=TEST_LANGUAGE,
    )
    uses.quota.record_audio = AsyncMock()
    return uses, speech, words


def _used_up(tier=UserTier.normal, **fields):
    today = datetime.now(timezone.utc).date().isoformat()
    return make_user(user_id=str(USER), tier=tier, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                     consumption=UserConsumption(consumption_date=today, audio_generated=3), **fields)


class TestWords:

    async def test_the_first_play_generates_and_stores_with_one_voice(self):
        uses, speech, words = _build(expression=_expression())

        result = await uses.clip(USER, EXPRESSION_ID, "word")

        assert isinstance(result, Clip) and result.audio == b"mp3"
        text, voice = speech.synthesize.await_args.args
        assert text == "il mare" and voice in VOICES["it"]
        assert len(words.docs) == 1 and words.docs[0]["voice"] == voice
        uses.quota.record_audio.assert_awaited_once()

    async def test_the_next_play_reuses_it_free_of_charge(self):
        uses, speech, words = _build(expression=_expression())
        await uses.clip(USER, EXPRESSION_ID, "word")

        again = await uses.clip(USER, EXPRESSION_ID, "word")

        assert again.audio == b"mp3"
        speech.synthesize.assert_awaited_once()
        uses.quota.record_audio.assert_awaited_once()
        assert len(words.docs) == 1

    async def test_casing_and_spacing_share_a_clip(self):
        assert word_key("it", "Il  Mare ") == word_key("it", "il mare")
        assert word_key("it", "il mare") != word_key("en", "il mare")

    async def test_a_stored_word_plays_even_when_the_daily_limit_is_used_up(self):
        uses, speech, _ = _build(expression=_expression())
        await uses.clip(USER, EXPRESSION_ID, "word")
        uses.users.get_user.return_value = _used_up()

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), Clip)

    async def test_a_word_without_a_generated_card_can_still_be_heard(self):
        uses, _, _ = _build(expression=_expression(card=False))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), Clip)

    async def test_the_telegram_file_id_comes_back_with_the_word(self):
        uses, _, _ = _build(expression=_expression())
        first = await uses.clip(USER, EXPRESSION_ID, "word")

        await uses.remember_telegram_file(first.word_key, "file-1")

        assert (await uses.clip(USER, EXPRESSION_ID, "word")).telegram_file_id == "file-1"


class TestOtherParts:

    @pytest.mark.parametrize("part, text", [("definition", "Grande distesa d'acqua."), ("example", "Andiamo al mare.")])
    async def test_are_generated_each_time_and_never_stored(self, part, text):
        uses, speech, words = _build(expression=_expression())

        await uses.clip(USER, EXPRESSION_ID, part)
        await uses.clip(USER, EXPRESSION_ID, part)

        assert speech.synthesize.await_count == 2
        assert speech.synthesize.await_args.args[0] == text
        assert uses.quota.record_audio.await_count == 2
        assert words.docs == []

    async def test_a_translation_speaks_in_its_own_language(self):
        uses, speech, _ = _build(expression=_expression())

        await uses.clip(USER, EXPRESSION_ID, "translation_0")

        text, voice = speech.synthesize.await_args.args
        assert text == "دریا" and voice in VOICES["fa"]

    async def test_a_translation_in_an_unknown_language_is_missing(self):
        uses, speech, _ = _build(expression=_expression())

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "translation_1"), PartMissing)
        speech.synthesize.assert_not_awaited()

    async def test_no_stored_card_means_no_such_part(self):
        uses, _, _ = _build(expression=_expression(card=False))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "definition"), PartMissing)


class TestRefusals:

    async def test_someone_elses_or_a_removed_card_is_not_found(self):
        uses, speech, _ = _build(expression=None)

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), CardNotFound)
        speech.synthesize.assert_not_awaited()

    async def test_the_daily_limit_stops_generating(self):
        uses, speech, _ = _build(expression=_expression(), user=_used_up())

        result = await uses.clip(USER, EXPRESSION_ID, "example")

        assert isinstance(result, QuotaExceeded) and result.limit == 3
        speech.synthesize.assert_not_awaited()

    async def test_an_own_llm_key_does_not_lift_the_limit(self):
        uses, _, _ = _build(expression=_expression(),
                            user=_used_up(api_config={"provider": "groq", "api_key": "k", "model": "m"}))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "example"), QuotaExceeded)

    async def test_an_admin_has_no_limit(self):
        uses, _, _ = _build(expression=_expression(), user=_used_up(tier=UserTier.admin))

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "example"), Clip)

    async def test_the_gate_can_refuse_right_before_generating(self):
        uses, speech, _ = _build(expression=_expression())
        refused = Throttled(retry_after=5)

        assert await uses.clip(USER, EXPRESSION_ID, "example", before_generation=lambda: refused) is refused
        speech.synthesize.assert_not_awaited()

    async def test_a_failing_service_costs_nothing_and_stores_nothing(self):
        uses, speech, words = _build(expression=_expression())
        speech.synthesize.side_effect = RuntimeError("403")

        assert isinstance(await uses.clip(USER, EXPRESSION_ID, "word"), SpeechFailed)
        uses.quota.record_audio.assert_not_awaited()
        assert words.docs == []


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
        uses, speech, _ = _build(expression=expression)

        assert part not in [p.part for p in await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID)]
        assert isinstance(await uses.clip(USER, EXPRESSION_ID, part), PartMissing)
        speech.synthesize.assert_not_awaited()

    async def test_a_card_that_is_gone_is_not_found(self):
        uses, _, _ = _build(expression=None)

        assert await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID) == CardNotFound()

    async def test_a_message_no_longer_waiting_for_a_grade_is_not_pending(self):
        uses, _, _ = _build(expression=_expression())

        assert await uses.parts(USER, EXPRESSION_ID, message_id=MESSAGE_ID + 1) == NotPending()


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
