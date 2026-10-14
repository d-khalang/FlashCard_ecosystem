"""
When a user should get the next scheduled review. Pure rules, no I/O.

Legacy rule: paused while `has_pending`.
New rule: paused while a current review is waiting and the user has not been seen
since it was sent. Any interaction resumes reviews, so an idle user is not spammed
and an active one is not left without reviews.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from flashcard.schemas.user import UserDB
from flashcard.utils.time import parse_iso


def interval_elapsed(user: UserDB, now: datetime) -> bool:
    """The user's review interval has passed since their last graded review."""
    if not user.last_reviewed_at:
        return True
    elapsed_seconds = (now - parse_iso(user.last_reviewed_at)).total_seconds()
    return elapsed_seconds >= user.review_interval_minutes * 60


def awaiting_answer(user: UserDB) -> bool:
    """A delivered card is waiting and the user has not interacted since it was sent."""
    review = user.current_review
    if review is None:
        return False
    if not user.last_seen_at:
        return True
    return parse_iso(user.last_seen_at) <= parse_iso(review.sent_at)


# How the legacy and new pause decisions relate for one user.
Comparison = Literal[
    "agree",                      # both paused or both free
    "resumed_by_interaction",     # legacy paused; user was seen after the card (intended change)
    "missing_current_review",     # legacy paused; no current review (backfill gap or removed card)
    "new_pauses",                 # legacy free; new rule would pause (unexpected: investigate)
]


def compare_pause(user: UserDB) -> Comparison:
    legacy_paused = user.has_pending
    new_paused = awaiting_answer(user)
    if legacy_paused == new_paused:
        return "agree"
    if new_paused:
        return "new_pauses"
    if user.current_review is None:
        return "missing_current_review"
    return "resumed_by_interaction"


@dataclass
class PauseComparison:
    counts: dict[str, int] = field(default_factory=dict)
    mismatches: list[tuple[str, str]] = field(default_factory=list)  # (user_id, comparison)

    def add(self, user: UserDB) -> None:
        comparison = compare_pause(user)
        self.counts[comparison] = self.counts.get(comparison, 0) + 1
        if comparison != "agree":
            self.mismatches.append((user.user_id, comparison))
