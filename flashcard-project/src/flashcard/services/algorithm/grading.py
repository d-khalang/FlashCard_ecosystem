from flashcard.schemas.expression import ExpressionStats
from flashcard.utils.time import now_utc

ALPHA = 0.30          # EWMA smoothing
PASS_THRESHOLD = 3    # >=3 counts as success

def calculate_new_stats(stats: ExpressionStats, grade: int) -> ExpressionStats:
    """
    The SRS stats of one direction after a grade (0-5), reviewed now.
    Matches the logic from the n8n Python node. Where they are stored (root
    for forward, `reverse_stats` for reverse) is the service's concern.
    """
    is_success = grade >= PASS_THRESHOLD

    return ExpressionStats(
        reps=stats.reps + (1 if is_success else 0),
        lapses=stats.lapses + (0 if is_success else 1),
        success_streak=(stats.success_streak + 1) if is_success else 0,
        ewma_grade=round(ALPHA * grade + (1.0 - ALPHA) * stats.ewma_grade, 4),
        last_grade=grade,
        last_review_at=now_utc(),
    )
