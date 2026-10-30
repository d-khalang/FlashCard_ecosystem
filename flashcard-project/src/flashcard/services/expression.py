import re
from datetime import datetime, timedelta
from typing import Optional, get_args

from flashcard.utils.time import iso_z, now_utc

from flashcard.schemas.expression import (
    MAX_GRADE, MIN_GRADE, Direction, Expression, ExpressionDB, ReviewCandidate, StoredCard,
)
from flashcard.schemas.user import UserId, stored_user_id
from flashcard.services.algorithm.priority import calculate_priority
from flashcard.services.algorithm.grading import calculate_new_stats
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import observe
from bson import ObjectId
from pymongo.collation import Collation, CollationStrength
from pydantic import ValidationError
from pymongo.errors import BulkWriteError, DuplicateKeyError

logger = get_logger(__name__)

# One card per user and value, ignoring case but not accents: "Ciao" == "ciao",
# "perché" != "perche". The database enforces it once the dedupe migration
# (flashcard.migrations.dedupe_expressions) has built the index.
UNIQUE_VALUE_INDEX = "user_value_unique_ci"
VALUE_COLLATION = Collation(locale="en", strength=CollationStrength.SECONDARY)
DUPLICATE_KEY = 11000

# Every read and remove uses this one definition of an active card. Documents saved
# before `status` existed have none and count as active; nothing sets another status yet.
ACTIVE = {"$in": ["active", None]}

class ExpressionService:
    def __init__(self, expressions):
        """`expressions`: the expression collection, the only data this service touches."""
        self.expressions = expressions

    async def search_expressions(
        self,
        user_id: UserId,
        query: str,
        *,
        limit: int = 50,
    ) -> list[Expression]:
        """
        Search a user's active expressions by value, case-insensitively.
        """
        normalized_query = query.strip()
        if not normalized_query or limit <= 0:
            return []

        escaped_query = re.escape(normalized_query)
        cursor = self.expressions.find(
            {
                "user_id": stored_user_id(user_id),
                "status": ACTIVE,
                "value": {"$regex": escaped_query, "$options": "i"},
            }
        )

        results: list[Expression] = []
        async for doc in cursor:
            expression = _read(doc)
            if expression is not None:
                results.append(expression)
            if len(results) >= limit:
                break

        return results

    async def add_expression(self, user_id: UserId, value: str) -> bool:
        """
        Adds a new expression if it doesn't already exist.
        1. Check for duplicates (case-insensitive)
        2. If not exists, insert the new expression document; the unique index
           rejects a concurrent save of the same value.

        Returns:
            bool: True if inserted, False if duplicate
        """
        # 1. Check for duplicates. Only needed until the unique index exists (contract step).
        # Escaping regex to prevent issues with special characters in 'value'
        escaped_value = re.escape(value)
        existing = await self.expressions.find_one({
            "user_id": stored_user_id(user_id),
            "value": {"$regex": f"^{escaped_value}$", "$options": "i"}
        })

        if existing:
            return False

        # 2. Insert Expression
        new_expression = ExpressionDB(
            user_id=stored_user_id(user_id),
            value=value,
            created_at=now_utc()
        )

        try:
            await self.expressions.insert_one(new_expression.model_dump())
        except DuplicateKeyError:
            # A concurrent save of the same value (double tap, retry) won the race.
            return False
        logger.info(f"Inserted new expression for user {user_id}: {value}")
        return True

    async def add_expressions_bulk(self, user_id: UserId, expressions: list[str]) -> list[str]:
        """
        Adds multiple expressions at once, ignoring duplicates.
        Returns the list of values that were actually inserted.
        """
        if not expressions:
            return []

        # 1. Drop repeats within the input, case-insensitively; the first spelling wins.
        seen, unique_inputs = set(), []
        for value in expressions:
            if value.lower() not in seen:
                seen.add(value.lower())
                unique_inputs.append(value)
        # Skip values already saved. Only needed until the unique index exists (contract step).
        regex_list = [re.compile(f"^{re.escape(v)}$", re.I) for v in unique_inputs]

        existing_cursor = self.expressions.find({
            "user_id": stored_user_id(user_id),
            "value": {"$in": regex_list}
        })
        
        # Create set of existing lowercased values for easy comparison
        existing_lower = set()
        async for doc in existing_cursor:
            existing_lower.add(doc['value'].lower())
            
        # 2. Filter new items
        new_items = []
        now = now_utc()
        
        to_insert = []
        for val in unique_inputs:
            if val.lower() not in existing_lower:
                new_items.append(val)
                # Prepare for bulk insert
                new_expr = ExpressionDB(
                    user_id=stored_user_id(user_id),
                    value=val,
                    created_at=now
                )
                to_insert.append(new_expr.model_dump())
        
        if not to_insert:
            return []
            
        # 3. Bulk Insert. Unordered, so a value the unique index rejects (saved
        # concurrently) does not stop the rest.
        try:
            await self.expressions.insert_many(to_insert, ordered=False)
        except BulkWriteError as error:
            write_errors = error.details.get("writeErrors", [])
            if any(e.get("code") != DUPLICATE_KEY for e in write_errors):
                raise
            rejected = {e["index"] for e in write_errors}
            new_items = [value for i, value in enumerate(new_items) if i not in rejected]

        logger.info(f"Bulk inserted {len(new_items)} expressions for user {user_id}")
        return new_items


    async def ensure_unique_value_index(self) -> None:
        """Build the unique (user_id, value) index. Fails while duplicates exist."""
        await self.expressions.create_index(
            [("user_id", 1), ("value", 1)],
            name=UNIQUE_VALUE_INDEX,
            unique=True,
            collation=VALUE_COLLATION,
        )

    async def remove_duplicates(self, expression_ids: list) -> int:
        """Migration only (dedupe_expressions): delete these cards. Returns how many."""
        result = await self.expressions.delete_many({"_id": {"$in": expression_ids}})
        return result.deleted_count

    async def get_all_expressions(self, user_id: UserId) -> list[str]:
        """
        The user's active expressions, each value once, oldest first.
        """
        cursor = self.expressions.find(
            {"user_id": stored_user_id(user_id), "status": ACTIVE}, {"value": 1}
        ).sort("created_at", 1)
        values: dict[str, None] = {}  # keeps first-seen order
        async for doc in cursor:
            if doc.get("value"):
                values.setdefault(doc["value"], None)
        return list(values)

    async def remove_expression(self, user_id: UserId, expression_id: str) -> bool:
        """
        Delete an active expression owned by the given user.
        """
        if not ObjectId.is_valid(expression_id):
            logger.warning(f"Invalid expression id received for removal: {expression_id}")
            return False

        result = await self.expressions.delete_one(
            {
                "_id": ObjectId(expression_id),
                "user_id": stored_user_id(user_id),
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
    async def get_review_candidate(self, user_id: UserId, review_mode: str) -> Optional[ReviewCandidate]:
        """
        Selects the best expression for review based on priority algorithm.
        Filters out expressions sent in the last 12 hours. `review_mode` is the user's
        setting ("dual" also scores the reverse direction); users are not this service's data.
        An unreadable card is logged and skipped.
        """
        #TODO: change 12 hours to get from a config file
        cutoff = now_utc() - timedelta(hours=12)
        # MongoDB compares only values of the same type, so until `convert_dates` has run,
        # each condition is given for dates and for the legacy ISO text.
        before_cutoff = [{"$lt": cutoff}, {"$lt": iso_z(cutoff)}]

        # Last send/grade before the cutoff; never interacted: created_at is the reference.
        query = {
            "user_id": stored_user_id(user_id),
            "status": ACTIVE,
            "$or": [
                *({"last_activity_at": condition} for condition in before_cutoff),
                *({"last_activity_at": None, "created_at": condition} for condition in before_cutoff),
            ]
        }

        #TODO: change to scheduled priority setter on all items of expressions
        # The highest priority over every candidate and direction wins.
        directions: tuple[Direction, ...] = ("forward", "reverse") if review_mode == "dual" else ("forward",)
        best: Optional[ReviewCandidate] = None
        max_priority = -1.0
        async for doc in self.expressions.find(query):
            expression = _read(doc)
            if expression is None:
                continue
            for direction in directions:
                priority = calculate_priority(expression.stats(direction), expression.created_at)
                if priority > max_priority:
                    max_priority = priority
                    best = ReviewCandidate(expression=expression, direction=direction)
        return best

    async def update_expression_sent(
        self, expression_id: str, message_id: int, last_card: Optional[StoredCard] = None,
    ):
        """
        Updates the expression after it has been sent to the user.
        `last_card` (a freshly generated card) replaces the stored one in the same write.
        """
        now = now_utc()
        fields = {
            "last_sent_at": now,
            "last_activity_at": now,
            "pending_message_id": message_id,
        }
        if last_card is not None:
            fields["last_card"] = last_card.model_dump()
        await self.expressions.update_one({"_id": ObjectId(expression_id)}, {"$set": fields})

    async def grade_expression(self, user_id: UserId, expression_id: str, grade: int, direction: str = "forward") -> bool:
        """
        Updates the graded direction's stats. False when the card does not exist (or
        cannot be read); raises ValueError for an out-of-range grade or unknown
        direction (nothing is written).
        """
        if type(grade) is not int or not MIN_GRADE <= grade <= MAX_GRADE:
            raise ValueError(f"grade must be an integer {MIN_GRADE}-{MAX_GRADE}, got {grade!r}")
        if direction not in get_args(Direction):
            raise ValueError(f"direction must be one of {get_args(Direction)}, got {direction!r}")

        doc = await self.expressions.find_one(
            {"_id": ObjectId(expression_id), "user_id": stored_user_id(user_id)}
        )
        expression = _read(doc) if doc else None
        if expression is None:
            logger.warning(f"Expression {expression_id} not found for user {user_id} during grading")
            return False

        stats = calculate_new_stats(expression.stats(direction), grade)
        if direction == "reverse":
            updates = {"reverse_stats": stats.model_dump()}
        else:
            # Forward stats live at the root; their review time is `last_interaction_at`.
            updates = stats.model_dump(exclude={"last_review_at"})
            updates["last_interaction_at"] = stats.last_review_at
        # Global cooldown, and the card is no longer waiting for an answer.
        updates["last_activity_at"] = stats.last_review_at
        updates["pending_message_id"] = None

        await self.expressions.update_one({"_id": ObjectId(expression_id)}, {"$set": updates})
        return True


def _read(doc: dict) -> Optional[Expression]:
    """The stored expression, or None (logged) if the document cannot be read."""
    try:
        return Expression.model_validate(doc)
    except ValidationError:
        logger.warning("Skipping unreadable expression %s", doc.get("_id"), exc_info=True)
        return None
