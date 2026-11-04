"""
Settings use cases: read and change a user's learning preferences.

Every setter raises ValueError for invalid input, because values can come from
forged callback data. Inputs are typed `str` because they are untrusted; the
allowed values are enforced by UserService's setters, and the return types are
narrowed only after that check. These use cases parse user input (language names)
first. Callers own presentation (labels, flags, keyboards).
"""
from typing import Optional, cast, get_args

from flashcard.schemas.user import UserId
from flashcard.schemas.languages import NONE_MAP, LanguageLevel, normalize_language_input
from flashcard.schemas.user import MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, ReviewMode, UserDB
from flashcard.services.user import UserService


class SettingsUseCases:
    def __init__(self, user_service: UserService):
        self.users = user_service

    async def get(self, user_id: UserId) -> UserDB:
        return await self.users.get_user(user_id)

    async def update(self, user_id: UserId, changes: dict) -> UserDB:
        """
        Apply several settings at once (the Mini App's settings screen) and return the user.
        Everything is checked first, so a bad value changes nothing; raises ValueError for it.
        `secondary_language` None turns it off.
        """
        _check_changes(changes)
        if "target_level" in changes:
            await self.set_level(user_id, changes["target_level"])
        if "primary_language" in changes:
            await self.set_primary_language(user_id, changes["primary_language"])
        if "secondary_language" in changes:
            value = changes["secondary_language"]
            await self.set_secondary_language(user_id, "none" if value is None else value)
        if "review_mode" in changes:
            await self.set_review_mode(user_id, changes["review_mode"])
        if "review_interval_minutes" in changes:
            await self.set_interval(user_id, changes["review_interval_minutes"])
        if "is_active" in changes:
            await self.set_active(user_id, changes["is_active"])
        return await self.get(user_id)

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


SETTING_FIELDS = (
    "target_level", "primary_language", "secondary_language", "review_mode", "review_interval_minutes",
    "is_active",
)


def _check_changes(changes: dict) -> None:
    """Raises ValueError for any change UserService would refuse, before anything is written."""
    unknown = set(changes) - set(SETTING_FIELDS)
    if unknown:
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    if "target_level" in changes and changes["target_level"] not in get_args(LanguageLevel):
        raise ValueError(f"Unknown level: {changes['target_level']!r}")
    if "review_mode" in changes and changes["review_mode"] not in get_args(ReviewMode):
        raise ValueError(f"Unknown review mode: {changes['review_mode']!r}")
    if "review_interval_minutes" in changes:
        minutes = changes["review_interval_minutes"]
        if type(minutes) is not int or not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValueError(f"Interval must be {MIN_INTERVAL_MINUTES}-{MAX_INTERVAL_MINUTES} minutes")
    if "is_active" in changes and type(changes["is_active"]) is not bool:
        raise ValueError("is_active must be a bool")
    if "primary_language" in changes:
        _language_code(changes["primary_language"], none_allowed=False)
    if changes.get("secondary_language") is not None:
        _language_code(changes["secondary_language"], none_allowed=True)


def _language_code(text: str, *, none_allowed: bool) -> str:
    # normalize_language_input passes non-strings through (e.g. None for a sticker).
    if not isinstance(text, str):
        raise ValueError(f"Language must be text: {text!r}")
    return normalize_language_input(text, none_allowed=none_allowed)
