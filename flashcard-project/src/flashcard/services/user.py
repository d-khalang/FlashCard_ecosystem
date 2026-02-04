from datetime import datetime
from typing import Optional, Union
from flashcard.utils.logger import get_logger
from flashcard.schemas.user import UserDB

logger = get_logger(__name__)

class UserService:
    def __init__(self, cols: dict):
        self.cols = cols

    async def update_user_last_push(self, user_id: Union[str, int]):
        """
        Updates the user's last_push_at timestamp.
        """
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "last_push_at": datetime.now().isoformat(),
                    "has_pending": True 
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
