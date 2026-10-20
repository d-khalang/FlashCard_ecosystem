from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Union, Dict, TYPE_CHECKING, get_args
from flashcard.utils.logger import get_logger
from flashcard.schemas.languages import LANGUAGE_DATA, LanguageLevel
from flashcard.schemas.user import (
    MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, NO_LANGUAGE, ReviewMode, UserDB, UserTier,
)
from flashcard.settings import settings
from flashcard.utils.time import iso_z, now_utc, parse_iso

if TYPE_CHECKING:
    from flashcard.language import UserDefaults
    from flashcard.services.consumption import ConsumptionService

logger = get_logger(__name__)

TIER_LIMITS: Dict[UserTier, Dict[str, int]] = {
    UserTier.normal: {
        "cards": settings.TIER_LIMITS_NORMAL_CARDS,
        "stories": settings.TIER_LIMITS_NORMAL_STORIES,
    },
    UserTier.digi: {
        "cards": settings.TIER_LIMITS_DIGI_CARDS,
        "stories": settings.TIER_LIMITS_DIGI_STORIES,
    },
    UserTier.plus: {
        "cards": settings.TIER_LIMITS_PLUS_CARDS,
        "stories": settings.TIER_LIMITS_PLUS_STORIES,
    },
    UserTier.admin: {
        "cards": settings.TIER_LIMITS_ADMIN_CARDS,
        "stories": settings.TIER_LIMITS_ADMIN_STORIES,
    },  # Effectively unlimited
}

# Normal-tier users get plus limits for this many days after created_at.
TRIAL_DAYS = 14


class UserService:
    def __init__(
        self,
        users,
        consumption_service: ConsumptionService | None = None,
        defaults: UserDefaults | None = None,
    ):
        """
        `users`: the users collection (profile, settings and onboarding fields).
        `defaults`: this instance's settings for users who have not chosen their own.
        """
        self.users = users
        self.consumption_service = consumption_service
        self.defaults = defaults.as_fields() if defaults else {}

    def _to_user(self, doc: dict) -> UserDB:
        """Missing settings fall back to this instance's defaults; stored values win."""
        return UserDB.model_validate({**self.defaults, **doc})

    async def active_users_reviewed_before(
        self,
        cutoff: str,
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
            "$or": [{"last_reviewed_at": None}, {"last_reviewed_at": {"$lt": cutoff}}],
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

    async def get_user(self, user_id: Union[str, int]) -> UserDB:
        """
        Retrieves the full user document.
        """
        doc = await self.users.find_one({"user_id": str(user_id)}) or {}
        if not doc:
            return self._to_user({"user_id": str(user_id)})

        return self._to_user(doc)

    async def set_target_level(self, user_id: Union[str, int], level: LanguageLevel) -> None:
        if level not in get_args(LanguageLevel):
            raise ValueError(f"Unknown level: {level!r}")
        await self._set(user_id, "target_level", level)

    async def set_review_interval(self, user_id: Union[str, int], minutes: int) -> None:
        if type(minutes) is not int or not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValueError(f"Interval must be {MIN_INTERVAL_MINUTES}-{MAX_INTERVAL_MINUTES} minutes: {minutes!r}")
        await self._set(user_id, "review_interval_minutes", minutes)

    async def set_primary_language(self, user_id: Union[str, int], code: str) -> None:
        if code not in LANGUAGE_DATA:
            raise ValueError(f"Unsupported language code: {code!r}")
        await self._set(user_id, "primary_language", code)

    async def set_secondary_language(self, user_id: Union[str, int], code: str) -> None:
        """A language code, or NO_LANGUAGE to turn it off."""
        if code != NO_LANGUAGE and code not in LANGUAGE_DATA:
            raise ValueError(f"Unsupported language code: {code!r}")
        await self._set(user_id, "secondary_language", code)

    async def set_review_mode(self, user_id: Union[str, int], mode: ReviewMode) -> None:
        if mode not in get_args(ReviewMode):
            raise ValueError(f"Unknown review mode: {mode!r}")
        await self._set(user_id, "review_mode", mode)

    async def set_active(self, user_id: Union[str, int], active: bool) -> None:
        """Pause or resume scheduled reviews. Idempotent: a repeated tap changes nothing."""
        if type(active) is not bool:
            raise ValueError(f"active must be a bool: {active!r}")
        await self._set(user_id, "is_active", active)
        logger.info(f"User {user_id} status set to {'Active' if active else 'Inactive'}")

    async def _set(self, user_id: Union[str, int], field: str, value) -> None:
        """Only for the validated setters above; never creates a user."""
        await self.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {field: value}},
        )

    async def advance_onboarding(self, user_id: Union[str, int], current_step: int) -> bool:
        """
        Advances the onboarding step if the user is at the expected step.
        Returns True if advanced, False if already past this step.
        """
        query = {"user_id": str(user_id)}
        if current_step == 0:
            query["$or"] = [{"onboarding_step": 0}, {"onboarding_step": {"$exists": False}}]
        else:
            query["onboarding_step"] = current_step

        result = await self.users.update_one(
            query,
            {"$set": {"onboarding_step": current_step + 1}}
        )
        return result.modified_count > 0

    async def record_seen(self, user_id: Union[str, int], username: Optional[str]):
        """
        Records that the user interacted with the bot, and syncs their Telegram username.

        The only writer that creates user documents, so `created_at` (the trial start)
        is always the first interaction. Every other writer updates existing users only.
        """
        current_iso = iso_z(now_utc())
        await self.users.update_one(
            {"user_id": str(user_id)},
            {
                "$set": {"username": username, "last_seen_at": current_iso},
                "$setOnInsert": {"created_at": current_iso},
            },
            upsert=True
        )

    async def backfill_created_at(self, user_id: Union[str, int], created_at: str) -> bool:
        """
        Migration only: set a missing `created_at`. Never overwrites one, so it can
        never move a trial start. True when it wrote.
        """
        result = await self.users.update_one(
            # Matches a missing field and an explicit null alike.
            {"user_id": str(user_id), "created_at": None},
            {"$set": {"created_at": created_at}},
        )
        return bool(getattr(result, "modified_count", 0))

    def _get_effective_limits(self, user: UserDB) -> Dict[str, int]:
        """
        Returns the tier-based limits, accounting for the trial for 'normal' users.
        """
        if user.tier == UserTier.admin:
            return TIER_LIMITS[UserTier.admin]

        # Check for trial period if normal
        if user.tier == UserTier.normal:
            if user.created_at is None:
                # Haven't saved or been pushed a card yet -> Trial is effectively starting or hasn't started
                return TIER_LIMITS[UserTier.plus]
                
            created_at = parse_iso(user.created_at)
            # Ensure it's offset-aware if needed, but parse_iso usually handles it
            trial_delta = now_utc() - created_at
            if trial_delta.days < TRIAL_DAYS:
                return TIER_LIMITS[UserTier.plus]
        
        return TIER_LIMITS.get(user.tier, TIER_LIMITS[UserTier.normal])

    def card_limit(self, user: UserDB) -> int:
        """Daily card generation limit for the user's tier and trial state."""
        return self._get_effective_limits(user)["cards"]

    def story_limit(self, user: UserDB) -> int:
        """Daily story generation limit for the user's tier and trial state."""
        return self._get_effective_limits(user)["stories"]

    def _get_today_usage(self, user: UserDB, metric: str) -> int:
        """
        Returns the user's usage for a specific metric today.
        Delegates daily-reset logic to ConsumptionService (single source of truth).
        """
        resolved = self.consumption_service.resolve_consumption(user.consumption)
        return getattr(resolved.system_api, metric, 0)

    def can_generate_card(self, user: UserDB, uses_own_key: bool = False) -> bool:
        """
        Checks if the user can generate a card today.
        """
        if uses_own_key or user.tier == UserTier.admin:
            return True
        
        limits = self._get_effective_limits(user)
        current_usage = self._get_today_usage(user, "cards_generated")
            
        return current_usage < limits["cards"]

    def can_generate_story(self, user: UserDB, uses_own_key: bool = False) -> bool:
        """
        Checks if the user can generate a story today.
        """
        if uses_own_key or user.tier == UserTier.admin:
            return True
            
        limits = self._get_effective_limits(user)
        current_usage = self._get_today_usage(user, "stories_generated")
            
        return current_usage < limits["stories"]
