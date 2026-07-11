from __future__ import annotations

import importlib
import re
from typing import Protocol

from pydantic import BaseModel, Field

from flashcard.settings import Settings, settings


class LanguageValidationResult(BaseModel):
    is_valid: bool
    normalized_text: str | None = None
    normalized_items: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    reason: str | None = None


class LanguageValidityChecker(Protocol):
    async def validate_expression(self, text: str) -> LanguageValidationResult:
        ...

    async def validate_import_items(
        self,
        items: list[str],
    ) -> LanguageValidationResult:
        ...


class BaseLanguageValidityChecker:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.strip().split())

    async def validate_expression(self, text: str) -> LanguageValidationResult:
        normalized = self._normalize_text(text)
        if not normalized:
            return LanguageValidationResult(is_valid=False, reason="empty")
        return LanguageValidationResult(is_valid=True, normalized_text=normalized)

    async def validate_import_items(
        self,
        items: list[str],
    ) -> LanguageValidationResult:
        normalized_items = [
            self._normalize_text(item)
            for item in items
            if self._normalize_text(item)
        ]
        if not normalized_items:
            return LanguageValidationResult(is_valid=False, reason="empty")
        return LanguageValidationResult(
            is_valid=True,
            normalized_items=normalized_items,
        )


class LatinScriptLanguageValidityChecker(BaseLanguageValidityChecker):
    """
    Conservative first-pass validator for Latin-script learning languages.

    It rejects clearly incompatible input, but deliberately does not attempt
    semantic language detection. The LLM prompt remains the stricter fallback.
    """

    _allowed_chars = re.compile(
        r"^[A-Za-z0-9À-ÖØ-öø-ÿĀ-žḀ-ỿ'’/\-\s.,;:!?()°]+$"
    )
    _letter = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-žḀ-ỿ]")

    def _is_valid_text_shape(self, text: str) -> bool:
        return bool(self._letter.search(text)) and bool(self._allowed_chars.match(text))

    async def validate_expression(self, text: str) -> LanguageValidationResult:
        normalized = self._normalize_text(text)
        if not normalized:
            return LanguageValidationResult(is_valid=False, reason="empty")
        if not self._is_valid_text_shape(normalized):
            return LanguageValidationResult(
                is_valid=False,
                normalized_text=normalized,
                reason="unsupported_characters",
            )
        return LanguageValidationResult(is_valid=True, normalized_text=normalized)

    async def validate_import_items(
        self,
        items: list[str],
    ) -> LanguageValidationResult:
        valid_items: list[str] = []
        rejected_items: list[str] = []

        for item in items:
            normalized = self._normalize_text(item)
            if not normalized:
                continue
            if self._is_valid_text_shape(normalized):
                valid_items.append(normalized)
            else:
                rejected_items.append(normalized)

        if not valid_items:
            return LanguageValidationResult(
                is_valid=False,
                normalized_items=[],
                suggestions=rejected_items[:3],
                reason="unsupported_characters",
            )

        return LanguageValidationResult(
            is_valid=True,
            normalized_items=valid_items,
            suggestions=rejected_items[:3],
            reason="partial_rejection" if rejected_items else None,
        )


class ItalianLanguageValidityChecker(LatinScriptLanguageValidityChecker):
    pass


# To use a custom language validator:
# 1. Inherit from BaseLanguageValidityChecker and implement custom validation rules.
#    Example:
#      class GermanLanguageValidityChecker(BaseLanguageValidityChecker):
#          async def validate_expression(self, text: str) -> LanguageValidationResult:
#              # your validation logic...
# 2. In your .env/settings config, set LANGUAGE_VALIDATOR to:
#      - Either a registered key (e.g. 'permissive', 'latin', 'italian')
#      - Or an import path to your custom class:
#          LANGUAGE_VALIDATOR="my_module.validators:GermanLanguageValidityChecker"
VALIDATOR_REGISTRY = {
    "permissive": BaseLanguageValidityChecker,
    "latin": LatinScriptLanguageValidityChecker,
    "italian": ItalianLanguageValidityChecker,
}


def _load_custom_validator(path: str):
    module_path, separator, attr_name = path.partition(":")
    if not separator:
        module_path, separator, attr_name = path.rpartition(".")
    if not module_path or not attr_name:
        raise ValueError(
            "Custom LANGUAGE_VALIDATOR must be 'module:ClassName' or "
            "'module.ClassName'"
        )

    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def get_language_validator(
    app_settings: Settings = settings,
) -> LanguageValidityChecker:
    configured = getattr(app_settings, "LANGUAGE_VALIDATOR", "auto").strip().lower()
    if configured == "auto":
        configured = (
            "italian"
            if getattr(app_settings, "LEARNING_LANGUAGE_CODE", "it").lower() == "it"
            else "latin"
        )

    validator_cls = VALIDATOR_REGISTRY.get(configured)
    if validator_cls is None:
        validator_cls = _load_custom_validator(getattr(app_settings, "LANGUAGE_VALIDATOR", "auto"))

    return validator_cls(app_settings)
