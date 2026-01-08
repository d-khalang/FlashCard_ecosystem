import re
from datetime import datetime
from typing import Optional, Union

from flashcard.schemas.expression import ExpressionDB
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

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

    async def add_expressions_bulk(self, user_id: Union[str, int], expressions: list[str]) -> list[str]:
        """
        Adds multiple expressions at once, ignoring duplicates.
        Returns the list of values that were actually inserted.
        """
        if not expressions:
            return []

        # 1. Normalize input: remove duplicates within the user input inside logic if needed,
        # but existing logic below handles one-by-one check against DB or bulk check.
        # Let's do a bulk check for existing items to minimize DB reads.
        
        # We need case-insensitive check. 
        # Constructing a large $or regex query can be heavy if list is huge, 
        # but for typical telegram message (< 4096 chars), it's reasonable (e.g. max ~50-100 items).
        
        unique_inputs = list(set(expressions))
        regex_list = [re.compile(f"^{re.escape(v)}$", re.I) for v in unique_inputs]
        
        existing_cursor = self.cols['expression'].find({
            "user_id": str(user_id),
            "value": {"$in": regex_list}
        })
        
        # Create set of existing lowercased values for easy comparison
        existing_lower = set()
        async for doc in existing_cursor:
            existing_lower.add(doc['value'].lower())
            
        # 2. Filter new items
        new_items = []
        current_iso = datetime.now().isoformat()
        
        to_insert = []
        for val in unique_inputs:
            if val.lower() not in existing_lower:
                new_items.append(val)
                # Prepare for bulk insert
                new_expr = ExpressionDB(
                    user_id=str(user_id),
                    value=val,
                    created_at=current_iso
                )
                to_insert.append(new_expr.model_dump())
        
        if not to_insert:
            return []
            
        # 3. Bulk Insert
        await self.cols['expression'].insert_many(to_insert)
        
        # 4. Update User Data (once)
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
        
        logger.info(f"Bulk inserted {len(new_items)} expressions for user {user_id}")
        return new_items


    async def get_all_expressions(self, user_id: Union[str, int], sort_by_time: bool = False) -> list[str]:
        """
        Retrieves all active expressions for a given user.
        :param sort_by_time: If True, returns expressions sorted by creation time (oldest first).
        """
        if sort_by_time:
            # Use find() and sort by created_at. 1 = Ascending (Oldest first)
            cursor = self.cols['expression'].find({"user_id": str(user_id)}).sort("created_at", 1)
            expressions = []
            async for doc in cursor:
                if 'value' in doc:
                    expressions.append(doc['value'])
            return expressions
        else:
            # Default: use distinct which is likely faster for uniqueness, 
            # though it doesn't guarantee specific order (UI handles alphabetical sort)
            expressions = await self.cols['expression'].distinct("value", {"user_id": str(user_id)})
            return expressions
