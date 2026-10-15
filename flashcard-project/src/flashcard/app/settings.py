"""
Settings use cases: read and change a user's learning preferences.

Every setter raises ValueError for invalid input, because values can come from
forged callback data. The allowed values are enforced by UserService's setters;
these use cases parse user input (language names) first. Callers own presentation
(labels, flags, keyboards).
"""
from typing import get_args

from flashcard.app.types import UserId
from flashcard.schemas.languages import LanguageLevel, normalize_language_input
from flashcard.schemas.user import ReviewMode, UserDB
from flashcard.services.user import UserService

LEVELS = get_args(LanguageLevel)


class SettingsUseCases:
    def __init__(self, user_service: UserService):
        self.users = user_service

    async def get(self, user_id: UserId) -> UserDB:
        return await self.users.get_user(user_id)

    async def set_level(self, user_id: UserId, level: str) -> str:
        await self.users.set_target_level(user_id, level)
        return level

    async def set_interval(self, user_id: UserId, minutes: int) -> int:
        await self.users.set_review_interval(user_id, minutes)
        return minutes

    async def set_primary_language(self, user_id: UserId, text: str) -> str:
        """Accepts a language name, alias or code; returns the saved code."""
        code = _language_code(text, none_allowed=False)
        await self.users.set_primary_language(user_id, code)
        return code

    async def set_secondary_language(self, user_id: UserId, text: str) -> str:
        """Like set_primary_language, but "none" turns it off (returns NO_LANGUAGE)."""
        code = _language_code(text, none_allowed=True)
        await self.users.set_secondary_language(user_id, code)
        return code

    async def toggle_review_mode(self, user_id: UserId) -> ReviewMode:
        user = await self.users.get_user(user_id)
        new_mode: ReviewMode = "dual" if user.review_mode == "standard" else "standard"
        await self.users.set_review_mode(user_id, new_mode)
        return new_mode

    async def toggle_active(self, user_id: UserId) -> bool:
        """Pause or resume scheduled reviews; returns True when now active."""
        return await self.users.toggle_active_status(user_id)


def _language_code(text: str, *, none_allowed: bool) -> str:
    # normalize_language_input passes non-strings through (e.g. None for a sticker).
    if not isinstance(text, str):
        raise ValueError(f"Language must be text: {text!r}")
    return normalize_language_input(text, none_allowed=none_allowed)
