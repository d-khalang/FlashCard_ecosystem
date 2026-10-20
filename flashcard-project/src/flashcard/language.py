"""
The language this instance teaches. One instance serves one learning language;
the composition root builds this once from settings and passes it down.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UserDefaults:
    """Settings a user has until they choose their own."""
    primary_language: str
    secondary_language: Optional[str]
    target_level: str

    def as_fields(self) -> dict:
        return {
            "primary_language": self.primary_language,
            "secondary_language": self.secondary_language,
            "target_level": self.target_level,
        }


@dataclass(frozen=True)
class LanguageConfig:
    code: str
    name: str
    flag: str
    ui_locale: str
    validator: str
    conjugation: bool
    user_defaults: UserDefaults

    @classmethod
    def from_settings(cls, settings) -> "LanguageConfig":
        return cls(
            code=settings.LEARNING_LANGUAGE_CODE,
            name=settings.LEARNING_LANGUAGE_NAME,
            flag=settings.LEARNING_LANGUAGE_FLAG,
            ui_locale=settings.UI_LOCALE,
            validator=settings.LANGUAGE_VALIDATOR,
            conjugation=settings.ENABLE_CONJUGATION,
            user_defaults=UserDefaults(
                primary_language=settings.DEFAULT_PRIMARY_LANGUAGE,
                secondary_language=settings.DEFAULT_SECONDARY_LANGUAGE,
                target_level=settings.DEFAULT_TARGET_LEVEL,
            ),
        )
