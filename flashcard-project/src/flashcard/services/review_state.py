from typing import Union

from flashcard.schemas.user import CurrentReview
from flashcard.utils.logger import get_logger
from flashcard.utils.time import iso_z, now_utc

logger = get_logger(__name__)


class ReviewStateStore:
    """
    Sole writer of the user's review state: `users.current_review`, the delivered
    card still waiting for a grade. A newer card replaces it.
    """

    def __init__(self, cols: dict):
        self.cols = cols

    async def record_sent(
        self,
        user_id: Union[str, int],
        expression_id: str,
        direction: str,
        message_id: int,
    ) -> None:
        review = CurrentReview(
            expression_id=expression_id,
            direction=direction,
            message_id=message_id,
            sent_at=iso_z(now_utc()),
        )
        await self.cols["users"].update_one(
            {"user_id": str(user_id)},
            {"$set": {"current_review": review.model_dump()}},
        )

    async def record_graded(self, user_id: Union[str, int], expression_id: str, direction: str) -> None:
        """Clears the current review only if this grade is for it; late grades of older cards leave it."""
        await self.cols["users"].update_one(
            {
                "user_id": str(user_id),
                "current_review.expression_id": expression_id,
                "current_review.direction": {"$in": [direction, "unknown"]},
            },
            {"$unset": {"current_review": ""}},
        )

    async def backfill_from_legacy(
        self,
        user_id: Union[str, int],
        expression_id: str,
        message_id: int,
        sent_at: str,
    ) -> bool:
        """
        Migration only: set the current review from legacy pending fields.
        Never overwrites one the bot has already written. True when it wrote.
        """
        review = CurrentReview(
            expression_id=expression_id,
            direction="unknown",
            message_id=message_id,
            sent_at=sent_at,
        )
        result = await self.cols["users"].update_one(
            # Matches a missing field and an explicit null alike.
            {"user_id": str(user_id), "current_review": None},
            {"$set": {"current_review": review.model_dump()}},
        )
        return bool(getattr(result, "modified_count", 0))

    async def record_removed(self, user_id: Union[str, int], expression_id: str) -> None:
        await self.cols["users"].update_one(
            {"user_id": str(user_id), "current_review.expression_id": expression_id},
            {"$unset": {"current_review": ""}},
        )
