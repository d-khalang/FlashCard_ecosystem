from typing import Optional, Union

from flashcard.schemas.review_attempt import GRADABLE_STATES, ReviewAttemptDB
from flashcard.utils.logger import get_logger
from flashcard.utils.time import iso_z, now_utc

logger = get_logger(__name__)


class ReviewAttemptStore:
    """
    Sole owner of the review_attempts collection: one document per delivered card.

    A user has at most one open attempt; sending a new card supersedes it.
    """

    def __init__(self, cols: dict):
        self.cols = cols

    async def ensure_indexes(self) -> None:
        collection = self.cols["review_attempts"]
        await collection.create_index(
            "user_id",
            name="one_open_attempt_per_user",
            unique=True,
            partialFilterExpression={"state": "open"},
        )
        await collection.create_index(
            [("user_id", 1), ("expression_id", 1), ("sent_at", -1)],
            name="user_expression_latest",
        )

    async def record_sent(
        self,
        user_id: Union[str, int],
        expression_id: str,
        direction: str,
        message_id: int,
    ) -> None:
        now = iso_z(now_utc())
        # Close the previous open attempt first so the unique open index holds.
        await self.cols["review_attempts"].update_many(
            {"user_id": str(user_id), "state": "open"},
            {"$set": {"state": "superseded", "closed_at": now}},
        )
        attempt = ReviewAttemptDB(
            user_id=str(user_id),
            expression_id=expression_id,
            direction=direction,
            message_id=message_id,
            sent_at=now,
        )
        await self.cols["review_attempts"].insert_one(attempt.model_dump())

    async def record_graded(
        self,
        user_id: Union[str, int],
        expression_id: str,
        direction: str,
        grade: int,
    ) -> bool:
        """
        Close the latest gradable attempt for this card. False when there is none,
        e.g. for cards sent before attempts were recorded.
        """
        latest = await self._latest_gradable(user_id, expression_id)
        if latest is None:
            return False
        # The grade callback knows the direction; it fills backfilled "unknown" ones.
        result = await self.cols["review_attempts"].update_one(
            {"_id": latest["_id"], "state": {"$in": list(GRADABLE_STATES)}},
            {"$set": {
                "state": "graded",
                "grade": grade,
                "direction": direction,
                "closed_at": iso_z(now_utc()),
            }},
        )
        return bool(getattr(result, "modified_count", 0))

    async def record_removed(self, user_id: Union[str, int], expression_id: str) -> None:
        await self.cols["review_attempts"].update_many(
            {
                "user_id": str(user_id),
                "expression_id": expression_id,
                "state": {"$in": list(GRADABLE_STATES)},
            },
            {"$set": {"state": "removed", "closed_at": iso_z(now_utc())}},
        )

    async def _latest_gradable(self, user_id: Union[str, int], expression_id: str) -> Optional[dict]:
        cursor = self.cols["review_attempts"].find({
            "user_id": str(user_id),
            "expression_id": expression_id,
            "state": {"$in": list(GRADABLE_STATES)},
        }).sort("sent_at", -1).limit(1)
        async for doc in cursor:
            return doc
        return None
