"""
Drill results (docs/verbs/contract.md section 5): one document per user and verb in `verb_practice`,
one entry per tense, keyed by tense id (ids hold no dots or `$`, so they are safe Mongo keys).
"""
from dataclasses import dataclass

from flashcard.schemas.user import UserId, stored_user_id
from flashcard.utils.time import now_utc


@dataclass(frozen=True)
class PracticeResult:
    infinitive: str
    tense_id: str
    score: int
    out_of: int
    missed: list[str]


class VerbPracticeService:
    def __init__(self, practice):
        """`practice`: the verb_practice collection."""
        self.practice = practice

    async def ensure_indexes(self) -> None:
        """One document per user and verb; a user's latest practice first."""
        await self.practice.create_index([("user_id", 1), ("infinitive", 1)], unique=True)
        await self.practice.create_index([("user_id", 1), ("updated_at", 1)])

    async def record(self, user_id: UserId, result: PracticeResult) -> None:
        """One finished drill: one upsert (`$set` the tense's last result, `$inc` its attempts)."""
        now = now_utc()
        tense = f"tenses.{result.tense_id}"
        await self.practice.update_one(
            {"user_id": stored_user_id(user_id), "infinitive": result.infinitive},
            {
                "$set": {
                    f"{tense}.last_score": result.score,
                    f"{tense}.out_of": result.out_of,
                    f"{tense}.last_at": now,
                    f"{tense}.missed": list(result.missed),
                    "updated_at": now,
                },
                "$inc": {f"{tense}.attempts": 1},
                "$max": {f"{tense}.best_score": result.score},
            },
            upsert=True,
        )
