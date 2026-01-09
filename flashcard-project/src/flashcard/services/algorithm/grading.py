from datetime import datetime, timezone

UTC = timezone.utc
ALPHA = 0.30          # EWMA smoothing
PASS_THRESHOLD = 3    # >=3 counts as success

def now_utc():
    return datetime.now(UTC)

def iso_z(ts: datetime) -> str:
    # Ensure it's UTC and format like '2023-01-01T12:00:00Z'
    return ts.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

def calculate_new_stats(doc: dict, grade: float) -> dict:
    """
    Calculates the new SRS stats for an expression based on the grade.
    Matches the logic from the n8n Python node.
    """
    # Copy relevant fields to avoid mutating original if needed
    reps_before = int(doc.get("reps") or 0)
    lapses_before = int(doc.get("lapses") or 0)
    streak_before = int(doc.get("success_streak") or 0)
    ewma_before = float(doc.get("ewma_grade") or 0.0)

    is_success = grade >= PASS_THRESHOLD
    
    new_reps = reps_before + (1 if is_success else 0)
    new_lapses = lapses_before + (0 if is_success else 1)
    new_streak = (streak_before + 1) if is_success else 0
    
    new_ewma = round(ALPHA * grade + (1.0 - ALPHA) * ewma_before, 4)
    
    updates = {
        "reps": new_reps,
        "lapses": new_lapses,
        "success_streak": new_streak,
        "ewma_grade": new_ewma,
        "last_grade": grade,
        "last_interaction_at": iso_z(now_utc()),
        "pending_message_id": None # clear pending
    }
    
    return updates
