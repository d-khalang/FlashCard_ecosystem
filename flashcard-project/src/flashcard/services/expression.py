import re
from datetime import datetime, timedelta
from typing import Optional, Union

from flashcard.utils.time import iso_z, now_utc

from flashcard.schemas.expression import ExpressionDB
from flashcard.services.algorithm.priority import calculate_priority
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
        current_iso = iso_z(now_utc())
        
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
        current_iso = iso_z(now_utc())
        
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

    async def get_review_candidate(self, user_id: Union[str, int]) -> Optional[dict]:
        """
        Selects the best expression for review based on priority algorithm.
        Filters out expressions sent in the last 8 hours.
        Returns dictionay with 'doc' (ExpressionDB) and 'direction' ('forward' or 'reverse')
        """
        # 0. Get user review mode
        user = await self.cols['users'].find_one({"user_id": str(user_id)})
        review_mode = user.get("review_mode", "standard") if user else "standard"
        
        # 1. Filter candidates
        # Active status (implicit if we only have active ones, but good to be explicit if we add status later)
        # Not sent in last 12 hours
        #TODO: change 12 hours to get from a config file
        cutoff_time = iso_z(now_utc() - timedelta(hours=12))
        
        # We find documents where last_activity_at is null OR last_activity_at < cutoff (New COOLDOWN field)
        
        query = {
            "user_id": str(user_id),
            "$or": [
                {"last_activity_at": None},
                {"last_activity_at": {"$lt": cutoff_time}}
            ]
        }
        
        cursor = self.cols['expression'].find(query)
        candidates = []
        async for doc in cursor:
            candidates.append(doc)
            
        if not candidates:
            return None
            
        #TODO: change to scheduled priority setter on all items of expressions
        # 2. Calculate priority for each
        # We select the one with Max priority
        best_candidate = None
        best_direction = "forward"
        max_priority = -1.0
        
        for doc in candidates:
            # 2a. Forward Priority
            p_fwd = calculate_priority(doc)
            
            if p_fwd > max_priority:
                max_priority = p_fwd
                best_candidate = doc
                best_direction = "forward"
                
            # 2b. Reverse Priority (if Dual Mode)
            if review_mode == "dual":
                # Ensure reverse_stats exists or use defaults (simulated new item)
                rev_stats = doc.get("reverse_stats") or {"reps": 0, "ewma_grade": 0.0, "success_streak": 0, "lapses": 0}
                p_rev = calculate_priority(rev_stats)
                
                if p_rev > max_priority:
                    max_priority = p_rev
                    best_candidate = doc
                    best_direction = "reverse"
                
        if best_candidate:
            return {
                "doc": best_candidate,
                "direction": best_direction
            }
        return None

    async def update_expression_sent(self, expression_id: str, message_id: int):
        """
        Updates the expression after it has been sent to the user.
        """
        from bson import ObjectId
        await self.cols['expression'].update_one(
            {"_id": ObjectId(expression_id)},
            {
                "$set": {
                    "last_sent_at": iso_z(now_utc()),
                    "last_activity_at": iso_z(now_utc()),
                    "pending_message_id": message_id
                }
            }
        )

    async def update_user_last_push(self, user_id: Union[str, int]):
        """
        Updates the user's last_push_at timestamp.
        """
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "last_push_at": iso_z(now_utc()),
                    "has_pending": True 
                }
            },
            upsert=True
        )

    async def grade_expression(self, user_id: str, expression_id: str, grade: int, direction: str = "forward") -> Optional[dict]:
        """
        Updates the expression with the new grade stats.
        """
        from bson import ObjectId
        from flashcard.services.algorithm.grading import calculate_new_stats

        if not (0 <= grade <= 5):
            logger.warning(f"Invalid grade {grade} for user {user_id}")
            return None

        # 1. Get current document
        doc = await self.cols['expression'].find_one(
            {"_id": ObjectId(expression_id), "user_id": str(user_id)}
        )
        
        if not doc:
            logger.warning(f"Expression {expression_id} not found for user {user_id} during grading")
            return None
            
        # 2. Calculate updates
        is_reverse = direction == "reverse"
        # For reverse, we pass the existing reverse_stats (or empty dict which implies new)
        stats_input = doc if not is_reverse else (doc.get("reverse_stats") or {})
        
        updates_dict = calculate_new_stats(stats_input, float(grade), is_reverse=is_reverse)
        
        # 3. Apply Updates
        mongo_updates = {}
        if is_reverse:
             # Need to set fields under "reverse_stats." prefix
             for k, v in updates_dict.items():
                mongo_updates[f"reverse_stats.{k}"] = v
        else:
            mongo_updates = updates_dict

        # Global updates (Cooldown + Clear Pending)
        mongo_updates["last_activity_at"] = iso_z(now_utc())
        mongo_updates["pending_message_id"] = None
            
        await self.cols['expression'].update_one(
            {"_id": ObjectId(expression_id)},
            {"$set": mongo_updates}
        )
        
        # 4. Update User (has_pending = False)
        # Only clear pending if this was the pending item? 
        # For now assume mostly one flow.
        await self.cols['users'].update_one(
            {"user_id": str(user_id)},
            {"$set": {"has_pending": False}}
        )
        
        # Return updated document (merged) for UI - approximate sync
        # Note: this might not be perfect in-memory representation but enough for immediate feedback if needed
        return doc # UI usually doesn't need the exact new stats immediately
