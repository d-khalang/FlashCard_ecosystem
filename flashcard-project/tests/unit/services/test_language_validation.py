import pytest

from flashcard.services.language_validation import (
    BaseLanguageValidityChecker,
    ItalianLanguageValidityChecker,
    get_language_validator,
)


async def test_permissive_validator_normalizes_expression():
    validator = BaseLanguageValidityChecker()

    result = await validator.validate_expression("  fare   colazione  ")

    assert result.is_valid is True
    assert result.normalized_text == "fare colazione"


async def test_italian_validator_rejects_unsupported_script():
    validator = ItalianLanguageValidityChecker()

    result = await validator.validate_expression("こんにちは")

    assert result.is_valid is False
    assert result.reason == "unsupported_characters"


@pytest.mark.parametrize(
    "text",
    [
        "perché",
        "città",
        "però",
        "virtù",
        "1° piano",
        "È già l'ora",
    ],
)
async def test_italian_validator_accepts_common_italian_characters(text):
    validator = ItalianLanguageValidityChecker()

    result = await validator.validate_expression(text)

    assert result.is_valid is True
    assert result.normalized_text == text


async def test_italian_validator_filters_import_items():
    validator = ItalianLanguageValidityChecker()

    result = await validator.validate_import_items(["andare", "こんにちは", "perché"])

    assert result.is_valid is True
    assert result.normalized_items == ["andare", "perché"]
    assert result.suggestions == ["こんにちは"]


def test_auto_validator_uses_italian_for_italian_settings():
    class DummySettings:
        LANGUAGE_VALIDATOR = "auto"
        LEARNING_LANGUAGE_CODE = "it"

    validator = get_language_validator(DummySettings())

    assert isinstance(validator, ItalianLanguageValidityChecker)
