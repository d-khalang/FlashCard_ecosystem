from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union, Dict, TYPE_CHECKING, get_args
from flashcard.utils.logger import get_logger
from flashcard.schemas.languages import LANGUAGE_DATA, LanguageLevel
from flashcard.schemas.user import (
    MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, NO_LANGUAGE, ReviewMode, UserDB, UserTier,
)
from flashcard.settings import settings
from flashcard.utils.time import iso_z, now_utc, parse_iso

if TYPE_CHECKING:
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
    def __init__(self, cols: dict, consumption_service: ConsumptionService | None = None):
        self.cols = cols
        self.consumption_service = consumption_service

    async def toggle_active_status(self, user_id: Union[str, int]) -> bool:
        """
        Toggles the user's active status.
        Returns the new status (True=Active, False=Inactive).
        """
        user_id_str = str(user_id)
        user = await self.cols['users'].find_one({"user_id": user_id_str})
        
        # Default to True if not present, so we toggle to False. 
        # If present, toggle existing.
        current_status = user.get("is_active", True) if user else True
        new_status = not current_status
        
        await self.cols['users'].update_one(
            {"user_id": user_id_str},
            {"$set": {"is_active": new_status}},
        )
        
        status_str = "Active" if new_status else "Inactive"
        logger.info(f"User {user_id} status toggled to {status_str}")
        return new_status

    async def get_user_status(self, user_id: Union[str, int]) -> bool:
        """
        Returns True if user is active, False otherwise.
        Default is True.
        """
        user = await self.cols['users'].find_one({"user_id": str(user_id)})
        if not user:
            return True
        return user.get("is_active", True)

    async def get_user(self, user_id: Union[str, int]) -> UserDB:
        """
        Retrieves the full user document.
        """
        doc = await self.cols['users'].find_one({"user_id": str(user_id)}) or {}
        if not doc:
            return UserDB(user_id=str(user_id))
            
        return UserDB.model_validate(doc)

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

    async def _set(self, user_id: Union[str, int], field: str, value) -> None:
        """Only for the validated setters above; never creates a user."""
        await self.cols['users'].update_one(
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

        result = await self.cols['users'].update_one(
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
        await self.cols['users'].update_one(
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
        result = await self.cols['users'].update_one(
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
