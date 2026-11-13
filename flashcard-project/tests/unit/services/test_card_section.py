"""
Regenerating one section of a card: the prompt, and the validation before anything is merged.
No provider is called.
"""
from unittest.mock import AsyncMock

import pytest

from flashcard.schemas.expression import CardSection, TranslationLine
from flashcard.services.llm.llm import InvalidCardSection, LLMGenerationResult, LLMService, validated_card_section

EN = TranslationLine(label="🇬🇧 EN", text="to go")
FA = TranslationLine(label="🇮🇷 FA", text="رفتن")
CURRENT = dict(definition="muoversi verso un luogo", translations=[EN, FA], example="Vado a scuola.")


def _result(**fields) -> CardSection:
    return CardSection(**{"definition": None, "translations": [], "example": None, **fields})


class TestValidation:

    def test_a_new_definition_is_kept_trimmed_and_alone(self):
        section = validated_card_section("definition", _result(definition="  spostarsi altrove  ",
                                                               example="ignored"), **CURRENT)

        assert section == _result(definition="spostarsi altrove")

    def test_a_new_example(self):
        assert validated_card_section("example", _result(example="Domani andiamo via."), **CURRENT).example == (
            "Domani andiamo via.")

    @pytest.mark.parametrize("section, fields", [
        ("definition", {"definition": None}), ("definition", {"definition": "   "}),
        ("example", {"example": ""}), ("example", {}),
        ("translations", {"translations": []}),
    ])
    def test_empty_results_are_refused(self, section, fields):
        with pytest.raises(InvalidCardSection):
            validated_card_section(section, _result(**fields), **CURRENT)

    @pytest.mark.parametrize("section, fields", [
        ("definition", {"definition": "Muoversi verso un luogo"}),
        ("example", {"example": " vado a scuola. "}),
    ])
    def test_the_same_text_is_not_a_refresh(self, section, fields):
        with pytest.raises(InvalidCardSection, match="unchanged"):
            validated_card_section(section, _result(**fields), **CURRENT)

    def test_translations_keep_their_labels_in_order(self):
        new = [TranslationLine(label="🇬🇧 EN", text=" to head "), TranslationLine(label="🇮🇷 FA", text="رهسپار شدن")]

        section = validated_card_section("translations", _result(translations=new), **CURRENT)

        assert [(t.label, t.text) for t in section.translations] == [("🇬🇧 EN", "to head"), ("🇮🇷 FA", "رهسپار شدن")]

    @pytest.mark.parametrize("new", [
        [TranslationLine(label="EN", text="to go"), FA],                       # label changed
        [FA, EN],                                                              # order changed
        [EN],                                                                  # one dropped
        [EN, FA, TranslationLine(label="🇩🇪 DE", text="gehen")],               # one added
        [EN, TranslationLine(label="🇮🇷 FA", text="  ")],                       # empty text
    ])
    def test_translations_that_lose_a_label_or_text_are_refused(self, new):
        with pytest.raises(InvalidCardSection):
            validated_card_section("translations", _result(translations=new), **CURRENT)

    def test_unchanged_translations_are_fine(self):
        assert validated_card_section("translations", _result(translations=[EN, FA]), **CURRENT).translations

    def test_a_missing_current_part_can_be_filled(self):
        current = dict(definition=None, translations=[EN], example=None)

        assert validated_card_section("example", _result(example="Nuova."), **current).example == "Nuova."


class TestGenerate:

    def _service(self, value: CardSection):
        service = LLMService.__new__(LLMService)
        service.learning_language_name = "Italian"
        service._generate_with_fallback = AsyncMock(return_value=LLMGenerationResult(
            value=value, provider="groq", provider_key="groq:test", model="m", fallback_triggered=False))
        return service

    async def test_the_prompt_names_the_expression_the_part_and_the_labels(self):
        service = self._service(_result(definition="spostarsi altrove"))

        section = await service.generate_card_section("definition", expression="andare", level="B1", **CURRENT)

        assert section.definition == "spostarsi altrove"
        call = service._generate_with_fallback.await_args.kwargs
        assert call["response_schema"] is CardSection
        prompt = call["contents"]
        for text in ("andare", "B1", "PART TO REWRITE: definition", "🇬🇧 EN: to go", "🇮🇷 FA: رفتن",
                     "muoversi verso un luogo", "Vado a scuola.", "Italian", "NEW sentence", "Keep each label EXACTLY"):
            assert text in prompt, text

    async def test_an_invalid_answer_raises_instead_of_returning(self):
        service = self._service(_result(translations=[TranslationLine(label="EN", text="x"), FA]))

        with pytest.raises(InvalidCardSection):
            await service.generate_card_section("translations", expression="andare", level="B1", **CURRENT)


def test_the_response_schema_is_strict_json_compatible():
    from flashcard.services.llm.llm import strict_json_schema

    schema = strict_json_schema(CardSection)

    assert set(schema["required"]) == {"definition", "translations", "example"}
    assert schema["additionalProperties"] is False
