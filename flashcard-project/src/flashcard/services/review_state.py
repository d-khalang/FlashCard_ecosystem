from flashcard.schemas.user import CurrentReview, LastAppGrade, UserId, stored_user_id
from flashcard.utils.logger import get_logger
from datetime import datetime

from flashcard.utils.time import now_utc

logger = get_logger(__name__)


class ReviewStateStore:
    """
    Sole writer of the user's review state:

    - `current_review`: the delivered card still waiting for a grade; a newer card replaces it.
    - `last_reviewed_at`: when the user last graded a card (starts the review interval).
    - `last_app_grade`: the last grade made in the Mini App, for one level of undo.
    - `has_pending`: legacy pause flag, removed in the contract step.
    """

    def __init__(self, users):
        """`users`: the users collection; this store owns only the review-state fields."""
        self.users = users

    async def mark_pending(self, user_id: UserId) -> None:
        """Legacy: a card was delivered; pause the scheduler until the user acts."""
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {"$set": {"has_pending": True}},
        )

    async def clear_pending(self, user_id: UserId) -> None:
        """Legacy: the user interacted; let the scheduler send the next review."""
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {"$set": {"has_pending": False}},
        )

    async def record_reviewed(self, user_id: UserId) -> None:
        """The user graded a card: start the review interval and clear the legacy pause."""
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {"$set": {"has_pending": False, "last_reviewed_at": now_utc()}},
        )

    async def record_sent(
        self,
        user_id: UserId,
        expression_id: str,
        direction: str,
        message_id: int,
    ) -> None:
        review = CurrentReview(
            expression_id=expression_id,
            direction=direction,
            message_id=message_id,
            sent_at=now_utc(),
        )
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {"$set": {"current_review": review.model_dump()}},
        )

    async def record_graded(self, user_id: UserId, expression_id: str, direction: str) -> None:
        """Clears the current review only if this grade is for it; late grades of older cards leave it."""
        await self.users.update_one(
            {
                "user_id": stored_user_id(user_id),
                "current_review.expression_id": expression_id,
                "current_review.direction": {"$in": [direction, "unknown"]},
            },
            {"$unset": {"current_review": ""}},
        )

    async def backfill_from_legacy(
        self,
        user_id: UserId,
        expression_id: str,
        message_id: int,
        sent_at: datetime,
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
            {"user_id": stored_user_id(user_id), "current_review": None},
            {"$set": {"current_review": review.model_dump()}},
        )
        return bool(getattr(result, "modified_count", 0))

    async def record_removed(self, user_id: UserId, expression_id: str) -> None:
        await self.users.update_one(
            {"user_id": stored_user_id(user_id), "current_review.expression_id": expression_id},
            {"$unset": {"current_review": ""}},
        )

    async def record_app_grade(self, user_id: UserId, grade: LastAppGrade) -> None:
        """Mini App: remember the last app grade, the one level of undo (it replaces the older one)."""
        await self.users.update_one(
            {"user_id": stored_user_id(user_id)},
            {"$set": {"last_app_grade": grade.model_dump()}},
        )

    async def restore_after_undo(self, user_id: UserId, grade: LastAppGrade) -> bool:
        """
        Mini App undo, after the card itself was put back: the card is the current review
        again, the review interval counts from the grade before it, and the undo hint is spent.
        Only while `grade` is still the stored hint. True when it wrote.
        """
        review = CurrentReview(
            expression_id=grade.expression_id,
            direction=grade.direction,
            message_id=grade.delivery_id,
            sent_at=grade.sent_at,
        )
        result = await self.users.update_one(
            {"user_id": stored_user_id(user_id), "last_app_grade.delivery_id": grade.delivery_id},
            {
                "$set": {"current_review": review.model_dump(), "last_reviewed_at": grade.previous_reviewed_at},
                "$unset": {"last_app_grade": ""},
            },
        )
        return bool(getattr(result, "modified_count", 0))

    async def clear_app_grade(self, user_id: UserId, delivery_id: int) -> None:
        """Mini App: the undo hint for this delivery can no longer be used."""
        await self.users.update_one(
            {"user_id": stored_user_id(user_id), "last_app_grade.delivery_id": delivery_id},
            {"$unset": {"last_app_grade": ""}},
        )
