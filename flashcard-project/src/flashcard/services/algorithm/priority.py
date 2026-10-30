import random
from datetime import datetime
from flashcard.schemas.expression import ExpressionStats
from flashcard.utils.time import UTC


def hours_since(dt: datetime | None) -> float:
    if not dt:
        return 0.0
    now = datetime.now(UTC)
    diff = (now - dt).total_seconds()
    return max(diff / 3600.0, 0.0)

# TODO: write performance test to compare output of various scenarios
# to be able to evaluate the priority function
def calculate_priority(stats: ExpressionStats, created_at: datetime | None = None) -> float:
    """
    Calculates the priority for review based on SRS factors.
    Priority = 0.4*Recency + 0.35*Difficulty + 0.10*Stability + 0.05*Novelty + 0.05*Lapses + Randomness

    `stats`: one direction's stats; recency counts from its last review, else from
    `created_at` (the expression's creation).
    """
    # 1) Recency (hours since last review, else since creation)
    last_dt = stats.last_review_at or created_at
    t = hours_since(last_dt) if last_dt else 200 # 200 hours is about 8 days to give new cards more chance to be reviewed
    recency = t / (24.0 + t)

    # 2) Difficulty (EWMA grade 0..5, where 0 is hard/unknown)
    # We want Difficulty score D to be high if grade is low.
    ewma = stats.ewma_grade
    D = 1.0 - (ewma / 5.0)

    # 3) Stability (success streak)
    # We want Stability score S to be high if streak is low (less stable).
    # Wait, in the n8n logic: S = 1.0 / (1.0 + streak)
    # So if streak is 0, S=1 (high priority). If streak is 10, S is low. Correct.
    streak = float(stats.success_streak)
    S = 1.0 / (1.0 + streak)

    # 4) Lapses (capped at 5)
    lapses = float(stats.lapses)
    L = min(lapses, 5.0) / 5.0

    # 5) Novelty (reps == 0)
    reps = stats.reps
    N = 1.0 if reps == 0 else 0.0

    # 6) Randomness
    eps = random.random() * 0.08

    priority_score = (
        0.40 * recency +
        0.35 * D +
        0.10 * S +
        0.05 * N +
        0.05 * L +
        eps
    )
    
    return priority_score
