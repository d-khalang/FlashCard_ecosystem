from typing import Literal, Optional

from pydantic import BaseModel, Field

# open: sent, waiting for a grade. superseded: a newer card was sent; still gradable.
# graded / removed: closed.
AttemptState = Literal["open", "superseded", "graded", "removed"]
# "unknown" only for attempts backfilled from legacy pending fields.
AttemptDirection = Literal["forward", "reverse", "unknown"]

GRADABLE_STATES: tuple[AttemptState, ...] = ("open", "superseded")


class ReviewAttemptDB(BaseModel):
    user_id: str = Field(..., description="User ID as string")
    expression_id: str = Field(..., description="Reviewed expression ObjectId as string")
    direction: AttemptDirection
    message_id: Optional[int] = Field(None, description="Telegram message that carries the card")
    state: AttemptState = "open"
    sent_at: str = Field(..., description="ISO timestamp of delivery")
    closed_at: Optional[str] = Field(None, description="ISO timestamp of grade, supersede or removal")
    grade: Optional[int] = None
