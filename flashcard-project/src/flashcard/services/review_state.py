from typing import Union

from flashcard.schemas.user import CurrentReview
from flashcard.utils.logger import get_logger
from flashcard.utils.time import iso_z, now_utc

logger = get_logger(__name__)


class ReviewStateStore:
    """
    Sole writer of the user's review state:

    - `current_review`: the delivered card still waiting for a grade; a newer card replaces it.
    - `last_reviewed_at`: when the user last graded a card (starts the review interval).
    - `has_pending`: legacy pause flag, removed in the contract step.
    """

    def __init__(self, users):
        """`users`: the users collection; this store owns only the review-state fields."""
        self.users = users

    async def mark_pending(self, user_id: Union[str, int]) -> None:
        """Legacy: a card was delivered; pause the scheduler until the user acts."""
        await self.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"has_pending": True}},
        )

    async def clear_pending(self, user_id: Union[str, int]) -> None:
        """Legacy: the user interacted; let the scheduler send the next review."""
        await self.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"has_pending": False}},
        )

    async def record_reviewed(self, user_id: Union[str, int]) -> None:
        """The user graded a card: start the review interval and clear the legacy pause."""
        await self.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"has_pending": False, "last_reviewed_at": iso_z(now_utc())}},
        )

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
        await self.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"current_review": review.model_dump()}},
        )

    async def record_graded(self, user_id: Union[str, int], expression_id: str, direction: str) -> None:
        """Clears the current review only if this grade is for it; late grades of older cards leave it."""
        await self.users.update_one(
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
        result = await self.users.update_one(
            # Matches a missing field and an explicit null alike.
            {"user_id": str(user_id), "current_review": None},
            {"$set": {"current_review": review.model_dump()}},
        )
        return bool(getattr(result, "modified_count", 0))

    async def record_removed(self, user_id: Union[str, int], expression_id: str) -> None:
        await self.users.update_one(
            {"user_id": str(user_id), "current_review.expression_id": expression_id},
            {"$unset": {"current_review": ""}},
        )
