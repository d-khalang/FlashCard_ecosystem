from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, TYPE_CHECKING, get_args
from flashcard.utils.logger import get_logger
from flashcard.schemas.languages import LANGUAGE_DATA, LanguageLevel
from flashcard.schemas.user import (
    MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, ReviewMode, UserDB, UserId, stored_user_id,
)
from flashcard.utils.time import now_utc

if TYPE_CHECKING:
    from flashcard.language import UserDefaults

logger = get_logger(__name__)


class UserService:
    def __init__(
        self,
        users,
        *,
        defaults: UserDefaults,
    ):
        """
        `users`: the users collection (profile, settings and onboarding fields).
        `defaults`: this instance's settings for users who have not chosen their own.
        """
        self.users = users
        self.defaults = defaults.as_fields()

    def _to_user(self, doc: dict) -> UserDB:
        """Missing settings fall back to this instance's defaults; stored values win."""
        return UserDB.model_validate({**self.defaults, **doc})

    async def active_users_reviewed_before(
        self,
        cutoff: datetime,
        *,
        exclude_pending: bool,
        on_unreadable: Callable[[str, Exception], None],
    ) -> list[UserDB]:
        """
        Active users never reviewed or last reviewed before `cutoff` (the scheduler's
        prefilter). `exclude_pending` drops users with the legacy `has_pending` flag.
        A document that cannot be read is passed to `on_unreadable` and skipped.
        """
        query = {
            "is_active": True,
            "$or": [
                {"last_reviewed_at": None},
                {"last_reviewed_at": {"$lt": cutoff}},
                # Legacy text (until `convert_dates` has run): the scheduler checks the
                # exact interval in Python, where an unreadable date is reported.
                {"last_reviewed_at": {"$type": "string"}},
            ],
        }
        if exclude_pending:
            query["has_pending"] = False
        return await self._read_users(query, on_unreadable)

    async def active_users_possibly_paused(self, on_unreadable: Callable[[str, Exception], None]) -> list[UserDB]:
        """Migration only (shadow compare): active users either pause rule could pause."""
        query = {"is_active": True, "$or": [{"has_pending": True}, {"current_review": {"$ne": None}}]}
        return await self._read_users(query, on_unreadable)

    async def _read_users(self, query: dict, on_unreadable: Callable[[str, Exception], None]) -> list[UserDB]:
        users = []
        async for doc in self.users.find(query):
            try:
                users.append(self._to_user(doc))
            except ValueError as e:  # pydantic's ValidationError is a ValueError
                on_unreadable(str(doc.get("user_id", "?")), e)
        return users

    async def get_user(self, user_id: UserId) -> UserDB:
        """
        Retrieves the full user document.
        """
        doc = await self.users.find_one({"user_id": stored_user_id(user_id)}) or {}
        if not doc:
            return self._to_user({"user_id": stored_user_id(user_id)})

        return self._to_user(doc)

    async def set_target_level(self, user_id: UserId, level: LanguageLevel) -> None:
        if level not in get_args(LanguageLevel):
            raise ValueError(f"Unknown level: {level!r}")
        await self._set(user_id, "target_level", level)

    async def set_review_interval(self, user_id: UserId, minutes: int) -> None:
        if type(minutes) is not int or not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValueError(f"Interval must be {MIN_INTERVAL_MINUTES}-{MAX_INTERVAL_MINUTES} minutes: {minutes!r}")
        await self._set(user_id, "review_interval_minutes", minutes)

    async def set_primary_language(self, user_id: UserId, code: str) -> None:
        if code not in LANGUAGE_DATA:
            raise ValueError(f"Unsupported language code: {code!r}")
        await self._set(user_id, "primary_language", code)

    async def set_secondary_language(self, user_id: UserId, code: Optional[str]) -> None:
        """A language code, or None to turn it off (stored as null)."""
        if code is not None and code not in LANGUAGE_DATA:
            raise ValueError(f"Unsupported language code: {code!r}")
        await self._set(user_id, "secondary_language", code)

    async def set_review_mode(self, user_id: UserId, mode: ReviewMode) -> None:
        if mode not in get_args(ReviewMode):
            raise ValueError(f"Unknown review mode: {mode!r}")
        await self._set(user_id, "review_mode", mode)

    async def set_active(self, user_id: UserId, active: bool) -> None:
        """Pause or resume scheduled reviews. Idempotent: a repeated tap changes nothing."""
        if type(active) is not bool:
            raise ValueError(f"active must be a bool: {active!r}")
        await self._set(user_id, "is_active", active)
        logger.info(f"User {user_id} status set to {'Active' if active else 'Inactive'}")

    async def _set(self, user_id: UserId, field: str, value) -> None:
        """Only for the validated setters above; never creates a user."""
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {"$set": {field: value}},
        )

    async def advance_onboarding(self, user_id: UserId, current_step: int) -> bool:
        """
        Advances the onboarding step if the user is at the expected step.
        Returns True if advanced, False if already past this step.
        """
        query = {"user_id": stored_user_id(user_id)}
        if current_step == 0:
            query["$or"] = [{"onboarding_step": 0}, {"onboarding_step": {"$exists": False}}]
        else:
            query["onboarding_step"] = current_step

        result = await self.users.update_one(
            query,
            {"$set": {"onboarding_step": current_step + 1}}
        )
        return result.modified_count > 0

    async def record_seen(self, user_id: UserId, username: Optional[str]):
        """
        Records that the user interacted with the bot, and syncs their Telegram username.

        The only writer that creates user documents, so `created_at` (the trial start)
        is always the first interaction. Every other writer updates existing users only.
        """
        now = now_utc()
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {
                "$set": {"username": username, "last_seen_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True
        )

    async def backfill_created_at(self, user_id: UserId, created_at: datetime) -> bool:
        """
        Migration only: set a missing `created_at`. Never overwrites one, so it can
        never move a trial start. True when it wrote.
        """
        result = await self.users.update_one(
            # Matches a missing field and an explicit null alike.
            {"user_id": stored_user_id(user_id), "created_at": None},
            {"$set": {"created_at": created_at}},
        )
        return bool(getattr(result, "modified_count", 0))
