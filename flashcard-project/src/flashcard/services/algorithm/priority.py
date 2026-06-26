import random
from datetime import datetime, timezone
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
UTC = timezone.utc

def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        logger.error(f"Failed to parse ISO timestamp: {ts}")
        return None

def hours_since(dt: datetime | None) -> float:
    if not dt:
        return 0.0
    now = datetime.now(UTC)
    diff = (now - dt).total_seconds()
    return max(diff / 3600.0, 0.0)

# TODO: write performance test to compare output of various scenarios
# to be able to evaluate the priority function
def calculate_priority(stats: dict) -> float:
    """
    Calculates the priority for review based on SRS factors.
    Priority = 0.4*Recency + 0.35*Difficulty + 0.10*Stability + 0.05*Novelty + 0.05*Lapses + Randomness
    
    Args:
        stats: A dict containing keys: 
               - last_interaction_at (or created_at)
               - ewma_grade
               - success_streak
               - lapses
               - reps
    """
    # 1) Recency (hours since last interaction)
    # For forward stats (root), last_interaction_at is used.
    # For reverse stats, we might use last_review_at. 
    # The caller ensures common keys or we handle fallback here.
    
    last_interaction = stats.get("last_interaction_at") or stats.get("last_review_at") or stats.get("created_at")
    last_dt = parse_iso(last_interaction)
    t = hours_since(last_dt) if last_dt else 200 # 200 hours is about 8 days to give new cards more chance to be reviewed
    recency = t / (24.0 + t)

    # 2) Difficulty (EWMA grade 0..5, where 0 is hard/unknown)
    # We want Difficulty score D to be high if grade is low.
    ewma = float(stats.get("ewma_grade") or 0)
    D = 1.0 - (ewma / 5.0)

    # 3) Stability (success streak)
    # We want Stability score S to be high if streak is low (less stable).
    # Wait, in the n8n logic: S = 1.0 / (1.0 + streak)
    # So if streak is 0, S=1 (high priority). If streak is 10, S is low. Correct.
    streak = float(stats.get("success_streak") or 0)
    S = 1.0 / (1.0 + streak)

    # 4) Lapses (capped at 5)
    lapses = float(stats.get("lapses") or 0)
    L = min(lapses, 5.0) / 5.0

    # 5) Novelty (reps == 0)
    reps = int(stats.get("reps") or 0)
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
