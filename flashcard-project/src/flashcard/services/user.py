from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union, Dict, TYPE_CHECKING
from flashcard.utils.logger import get_logger
from flashcard.schemas.user import UserDB, UserTier
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

class UserService:
    def __init__(self, cols: dict, consumption_service: ConsumptionService | None = None):
        self.cols = cols
        self.consumption_service = consumption_service

    async def update_user_last_push(self, user_id: Union[str, int]):
        """
        Updates the user's last_push_at timestamp.
        """
        current_iso = iso_z(now_utc())
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "last_push_at": current_iso,
                    "has_pending": True 
                },
                "$setOnInsert": {
                    "created_at": current_iso
                }
            },
            upsert=True
        )

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
            upsert=True
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

    async def update_setting(self, user_id: Union[str, int], field: str, value: any):
        """
        Updates a specific field in the user document.
        """
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {"$set": {field: value}},
            upsert=True
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

    async def update_username(self, user_id: Union[str, int], username: Optional[str]):
        """
        Updates the user's Telegram username.
        """
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {
                "$set": {"username": username},
                # Ensure created_at is initialized on first insert for this user.
                "$setOnInsert": {"created_at": iso_z(now_utc())},
            },
            upsert=True
        )

    def _get_effective_limits(self, user: UserDB) -> Dict[str, int]:
        """
        Returns the tier-based limits, accounting for the 14-day trial for 'normal' users.
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
            if trial_delta.days < 14:
                return TIER_LIMITS[UserTier.plus]
        
        return TIER_LIMITS.get(user.tier, TIER_LIMITS[UserTier.normal])

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
