import re
from datetime import datetime, timedelta
from typing import Optional, Union, get_args

from flashcard.utils.time import iso_z, now_utc

from flashcard.schemas.expression import MAX_GRADE, MIN_GRADE, Direction, ExpressionDB
from flashcard.services.algorithm.priority import calculate_priority
from flashcard.services.algorithm.grading import calculate_new_stats
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import observe
from bson import ObjectId

logger = get_logger(__name__)

# Every read and remove uses this one definition of an active card. Documents saved
# before `status` existed have none and count as active; nothing sets another status yet.
ACTIVE = {"$in": ["active", None]}

class ExpressionService:
    def __init__(self, expressions):
        """`expressions`: the expression collection, the only data this service touches."""
        self.expressions = expressions

    async def search_expressions(
        self,
        user_id: Union[str, int],
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """
        Search a user's active expressions by value, case-insensitively.
        """
        normalized_query = query.strip()
        if not normalized_query or limit <= 0:
            return []

        escaped_query = re.escape(normalized_query)
        cursor = self.expressions.find(
            {
                "user_id": str(user_id),
                "status": ACTIVE,
                "value": {"$regex": escaped_query, "$options": "i"},
            }
        )

        results: list[dict] = []
        async for doc in cursor:
            results.append(doc)
            if len(results) >= limit:
                break

        return results

    async def add_expression(self, user_id: Union[str, int], value: str) -> bool:
        """
        Adds a new expression if it doesn't already exist.
        1. Check for duplicates (case-insensitive)
        2. If not exists, insert the new expression document.
        
        Returns:
            bool: True if inserted, False if duplicate
        """
        # 1. Check for duplicates
        # Escaping regex to prevent issues with special characters in 'value'
        escaped_value = re.escape(value)
        existing = await self.expressions.find_one({
            "user_id": str(user_id),
            "value": {"$regex": f"^{escaped_value}$", "$options": "i"}
        })

        if existing:
            return False

        # 2. Insert Expression
        current_iso = iso_z(now_utc())
        new_expression = ExpressionDB(
            user_id=str(user_id),
            value=value,
            created_at=current_iso
        )

        await self.expressions.insert_one(new_expression.model_dump())
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
        # We need case-insensitive check. 
        unique_inputs = list(set(expressions))
        regex_list = [re.compile(f"^{re.escape(v)}$", re.I) for v in unique_inputs]
        
        existing_cursor = self.expressions.find({
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
        await self.expressions.insert_many(to_insert)
        
        logger.info(f"Bulk inserted {len(new_items)} expressions for user {user_id}")
        return new_items


    async def get_all_expressions(self, user_id: Union[str, int]) -> list[str]:
        """
        The user's active expressions, each value once, oldest first.
        """
        cursor = self.expressions.find(
            {"user_id": str(user_id), "status": ACTIVE}, {"value": 1}
        ).sort("created_at", 1)
        values: dict[str, None] = {}  # keeps first-seen order
        async for doc in cursor:
            if doc.get("value"):
                values.setdefault(doc["value"], None)
        return list(values)

    async def remove_expression(self, user_id: Union[str, int], expression_id: str) -> bool:
        """
        Delete an active expression owned by the given user.
        """
        if not ObjectId.is_valid(expression_id):
            logger.warning(f"Invalid expression id received for removal: {expression_id}")
            return False

        result = await self.expressions.delete_one(
            {
                "_id": ObjectId(expression_id),
                "user_id": str(user_id),
                "status": ACTIVE,
            }
        )
        deleted = bool(getattr(result, "deleted_count", 0))

        if deleted:
            logger.info(f"Removed expression {expression_id} for user {user_id}")
        else:
            logger.warning(f"Expression {expression_id} not removed for user {user_id}")

        return deleted

    @observe(name="ExpressionService.get_review_candidate")
    async def get_review_candidate(self, user_id: Union[str, int], review_mode: str) -> Optional[dict]:
        """
        Selects the best expression for review based on priority algorithm.
        Filters out expressions sent in the last 12 hours. `review_mode` is the user's
        setting ("dual" also scores the reverse direction); users are not this service's data.
        Returns dictionay with 'doc' (ExpressionDB) and 'direction' ('forward' or 'reverse')
        """
        # 1. Filter candidates
        # Active status (implicit if we only have active ones, but good to be explicit if we add status later)
        # Not sent in last 12 hours
        #TODO: change 12 hours to get from a config file
        cutoff_time = iso_z(now_utc() - timedelta(hours=12))
        
        # We find documents where last_activity_at is null OR last_activity_at < cutoff (New COOLDOWN field)
        
        query = {
            "user_id": str(user_id),
            "status": ACTIVE,
            "$or": [
                {"last_activity_at": {"$lt": cutoff_time}},
                # Never interacted: use created_at as cooldown reference
                {"last_activity_at": None, "created_at": {"$lt": cutoff_time}}
            ]
        }
        
        cursor = self.expressions.find(query)
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
                rev_stats = doc.get("reverse_stats") or {
                    "reps": 0,
                    "ewma_grade": 0.0,
                    "success_streak": 0,
                    "lapses": 0,
                    "created_at": doc.get("created_at")
                }
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
        await self.expressions.update_one(
            {"_id": ObjectId(expression_id)},
            {
                "$set": {
                    "last_sent_at": iso_z(now_utc()),
                    "last_activity_at": iso_z(now_utc()),
                    "pending_message_id": message_id
                }
            }
        )

    async def grade_expression(self, user_id: str, expression_id: str, grade: int, direction: str = "forward") -> Optional[dict]:
        """
        Updates the expression with the new grade stats.
        Returns None when the card does not exist; raises ValueError for an
        out-of-range grade or unknown direction (nothing is written).
        """
        if type(grade) is not int or not MIN_GRADE <= grade <= MAX_GRADE:
            raise ValueError(f"grade must be an integer {MIN_GRADE}-{MAX_GRADE}, got {grade!r}")
        if direction not in get_args(Direction):
            raise ValueError(f"direction must be one of {get_args(Direction)}, got {direction!r}")

        # 1. Get current document
        doc = await self.expressions.find_one(
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
            if doc.get("reverse_stats") is None:
                # reverse_stats is null — set the whole object at once
                mongo_updates["reverse_stats"] = updates_dict
            else:
                # reverse_stats exists — use dot-notation for partial update
                for k, v in updates_dict.items():
                    mongo_updates[f"reverse_stats.{k}"] = v
        else:
            mongo_updates = updates_dict

        # Global updates (Cooldown + Clear Pending)
        mongo_updates["last_activity_at"] = iso_z(now_utc())
        mongo_updates["pending_message_id"] = None
            
        await self.expressions.update_one(
            {"_id": ObjectId(expression_id)},
            {"$set": mongo_updates}
        )
        
        # Return updated document (merged) for UI - approximate sync
        # Note: this might not be perfect in-memory representation but enough for immediate feedback if needed
        return doc # UI usually doesn't need the exact new stats immediately
