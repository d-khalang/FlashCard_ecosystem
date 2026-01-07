import logging
import re
from datetime import datetime
from typing import Optional, Union

from flashcard.schemas.expression import ExpressionDB

logger = logging.getLogger(__name__)

class ExpressionService:
    def __init__(self, cols: dict):
        self.cols = cols

    async def add_expression(self, user_id: Union[str, int], value: str, message_date: datetime) -> bool:
        """
        Adds a new expression if it doesn't already exist.
        1. Check for duplicates (case-insensitive)
        2. If not exists:
           - Update user stats (last_push_at, has_pending=False)
           - Insert new expression document
        
        Returns:
            bool: True if inserted, False if duplicate
        """
        # 1. Check for duplicates
        # Escaping regex to prevent issues with special characters in 'value'
        escaped_value = re.escape(value)
        existing = await self.cols['expression'].find_one({
            "user_id": str(user_id),
            "value": {"$regex": f"^{escaped_value}$", "$options": "i"}
        })

        if existing:
            return False

        # 2. Update User Data
        current_iso = message_date.isoformat()
        
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "last_push_at": current_iso,
                    "has_pending": False
                }
            },
            upsert=True
        )

        # 3. Insert Expression
        new_expression = ExpressionDB(
            user_id=str(user_id),
            value=value,
            created_at=current_iso
        )

        await self.cols['expression'].insert_one(new_expression.model_dump())
        logger.info(f"Inserted new expression for user {user_id}: {value}")
        return True
