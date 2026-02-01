from datetime import datetime, timezone

UTC = timezone.utc
ALPHA = 0.30          # EWMA smoothing
PASS_THRESHOLD = 3    # >=3 counts as success

def now_utc():
    return datetime.now(UTC)

def iso_z(ts: datetime) -> str:
    # Ensure it's UTC and format like '2023-01-01T12:00:00Z'
    return ts.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

def calculate_new_stats(stats: dict, grade: float, is_reverse: bool = False) -> dict:
    """
    Calculates the new SRS stats for an expression based on the grade.
    Matches the logic from the n8n Python node.
    
    Args:
        stats: Current stats dict (from root or reverse_stats)
        grade: User grade (0-5)
        is_reverse: If True, returns dict for reverse_stats update. If False, for root.
    """
    # Copy relevant fields to avoid mutating original if needed
    reps_before = int(stats.get("reps") or 0)
    lapses_before = int(stats.get("lapses") or 0)
    streak_before = int(stats.get("success_streak") or 0)
    ewma_before = float(stats.get("ewma_grade") or 0.0)

    is_success = grade >= PASS_THRESHOLD
    
    new_reps = reps_before + (1 if is_success else 0)
    new_lapses = lapses_before + (0 if is_success else 1)
    new_streak = (streak_before + 1) if is_success else 0
    
    new_ewma = round(ALPHA * grade + (1.0 - ALPHA) * ewma_before, 4)
    
    current_time_iso = iso_z(now_utc())
    
    # Common stats
    new_stats_values = {
        "reps": new_reps,
        "lapses": new_lapses,
        "success_streak": new_streak,
        "ewma_grade": new_ewma,
        "last_grade": grade,
    }
    
    if is_reverse:
        new_stats_values["last_review_at"] = current_time_iso
        # For nested object updates, we return the whole object or let the caller construct the set
        # Here we return a flat dict that the service will convert to dot notation or nested object
        return new_stats_values
    else:
        # Standard/Forward updates (Root level)
        new_stats_values["last_interaction_at"] = current_time_iso
        new_stats_values["pending_message_id"] = None
        return new_stats_values
