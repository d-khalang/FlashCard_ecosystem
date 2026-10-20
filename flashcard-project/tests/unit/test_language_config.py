"""
Contract: the instance's language comes from one LanguageConfig built in the
composition root (docs/bot-architecture-refactor.md, #1), never from global settings.
"""
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import flashcard
from flashcard.language import LanguageConfig, UserDefaults
from flashcard.services.language_validation import (
    ItalianLanguageValidityChecker,
    LatinScriptLanguageValidityChecker,
    get_language_validator,
)
from flashcard.services.user import UserService
from tests.helpers import TEST_LANGUAGE

SRC = Path(flashcard.__file__).parent
LANGUAGE_SETTINGS = re.compile(
    r"\bsettings\.(LEARNING_LANGUAGE_\w+|UI_LOCALE|DEFAULT_PRIMARY_LANGUAGE|"
    r"DEFAULT_SECONDARY_LANGUAGE|DEFAULT_TARGET_LEVEL|ENABLE_CONJUGATION|LANGUAGE_VALIDATOR)\b"
)
# language.py builds the config; i18n is still a module-level singleton (#7).
MAY_READ_LANGUAGE_SETTINGS = {"language.py", "settings.py", "services/i18n.py"}


def test_only_language_config_reads_language_settings():
    readers = {path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py")
               if LANGUAGE_SETTINGS.search(path.read_text(encoding="utf-8"))}
    assert readers <= MAY_READ_LANGUAGE_SETTINGS


def test_from_settings_maps_every_language_setting():
    settings = SimpleNamespace(
        LEARNING_LANGUAGE_CODE="es", LEARNING_LANGUAGE_NAME="Spanish", LEARNING_LANGUAGE_FLAG="🇪🇸",
        UI_LOCALE="it", LANGUAGE_VALIDATOR="latin", ENABLE_CONJUGATION=False,
        DEFAULT_PRIMARY_LANGUAGE="fa", DEFAULT_SECONDARY_LANGUAGE="en", DEFAULT_TARGET_LEVEL="B2",
    )

    assert LanguageConfig.from_settings(settings) == LanguageConfig(
        code="es", name="Spanish", flag="🇪🇸", ui_locale="it", validator="latin", conjugation=False,
        user_defaults=UserDefaults(primary_language="fa", secondary_language="en", target_level="B2"),
    )


def test_auto_validator_uses_latin_for_other_languages():
    validator = get_language_validator(replace(TEST_LANGUAGE, validator="auto", code="es"))

    assert type(validator) is LatinScriptLanguageValidityChecker


def test_validator_receives_the_language():
    validator = get_language_validator(replace(TEST_LANGUAGE, validator="italian"))

    assert isinstance(validator, ItalianLanguageValidityChecker)
    assert validator.language == replace(TEST_LANGUAGE, validator="italian")


def _user_service(doc):
    users = MagicMock()
    users.find_one = AsyncMock(return_value=doc)
    defaults = UserDefaults(primary_language="fa", secondary_language="en", target_level="C1")
    return UserService(users=users, defaults=defaults)


async def test_new_user_gets_the_instance_defaults():
    user = await _user_service(None).get_user(1)

    assert (user.primary_language, user.secondary_language, user.target_level) == ("fa", "en", "C1")


async def test_stored_settings_win_over_instance_defaults():
    doc = {"user_id": "1", "primary_language": "it", "secondary_language": None, "target_level": "A1"}

    user = await _user_service(doc).get_user(1)

    assert (user.primary_language, user.secondary_language, user.target_level) == ("it", None, "A1")


async def test_missing_stored_settings_fall_back_to_instance_defaults():
    user = await _user_service({"user_id": "1", "target_level": "B1"}).get_user(1)

    assert (user.primary_language, user.secondary_language, user.target_level) == ("fa", "en", "B1")
