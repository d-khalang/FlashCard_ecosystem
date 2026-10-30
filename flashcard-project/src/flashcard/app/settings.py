"""
Settings use cases: read and change a user's learning preferences.

Every setter raises ValueError for invalid input, because values can come from
forged callback data. Inputs are typed `str` because they are untrusted; the
allowed values are enforced by UserService's setters, and the return types are
narrowed only after that check. These use cases parse user input (language names)
first. Callers own presentation (labels, flags, keyboards).
"""
from typing import Optional, cast

from flashcard.schemas.user import UserId
from flashcard.schemas.languages import NONE_MAP, LanguageLevel, normalize_language_input
from flashcard.schemas.user import ReviewMode, UserDB
from flashcard.services.user import UserService


class SettingsUseCases:
    def __init__(self, user_service: UserService):
        self.users = user_service

    async def get(self, user_id: UserId) -> UserDB:
        return await self.users.get_user(user_id)

    async def set_level(self, user_id: UserId, level: str) -> LanguageLevel:
        await self.users.set_target_level(user_id, level)
        return cast(LanguageLevel, level)  # validated by the setter above

    async def set_interval(self, user_id: UserId, minutes: int) -> int:
        await self.users.set_review_interval(user_id, minutes)
        return minutes

    async def set_primary_language(self, user_id: UserId, text: str) -> str:
        """Accepts a language name, alias or code; returns the saved code."""
        code = _language_code(text, none_allowed=False)
        await self.users.set_primary_language(user_id, code)
        return code

    async def set_secondary_language(self, user_id: UserId, text: str) -> Optional[str]:
        """Like set_primary_language, but "none" (or "no") turns it off and returns None."""
        code = _language_code(text, none_allowed=True)
        if code in NONE_MAP:
            code = None
        await self.users.set_secondary_language(user_id, code)
        return code

    async def set_review_mode(self, user_id: UserId, mode: str) -> ReviewMode:
        """Idempotent: the button names the mode to switch to, so a repeated tap changes nothing."""
        await self.users.set_review_mode(user_id, mode)
        return cast(ReviewMode, mode)  # validated by the setter above

    async def toggle_review_mode(self, user_id: UserId) -> ReviewMode:
        """
        Only for settings menus sent before buttons named their target mode
        (callback value "toggle"). Reads then writes, so it is not atomic.
        """
        user = await self.users.get_user(user_id)
        return await self.set_review_mode(user_id, "dual" if user.review_mode == "standard" else "standard")

    async def set_active(self, user_id: UserId, active: bool) -> bool:
        """Pause (False) or resume (True) scheduled reviews; idempotent."""
        await self.users.set_active(user_id, active)
        return active


def _language_code(text: str, *, none_allowed: bool) -> str:
    # normalize_language_input passes non-strings through (e.g. None for a sticker).
    if not isinstance(text, str):
        raise ValueError(f"Language must be text: {text!r}")
    return normalize_language_input(text, none_allowed=none_allowed)
