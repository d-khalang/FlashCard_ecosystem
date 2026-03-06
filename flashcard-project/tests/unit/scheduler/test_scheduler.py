"""
Unit tests for the scheduler module.

Tests:
  - find_users_due_for_review: filtering logic (active, pending, interval)
  - send_admin_metrics: report formatting, message splitting
"""
import asyncio
import json
from datetime import timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from flashcard.schemas.user import UserDB
from flashcard.utils.time import now_utc, iso_z
from tests.helpers import AsyncCursorMock as _AsyncCursor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_doc(user_id="123", is_active=True, has_pending=False,
                   last_reviewed_at=None, review_interval_minutes=30, **extra):
    """Create a user doc that UserDB.model_validate can accept."""
    doc = {
        "user_id": user_id,
        "is_active": is_active,
        "has_pending": has_pending,
        "last_reviewed_at": last_reviewed_at,
        "review_interval_minutes": review_interval_minutes,
    }
    doc.update(extra)
    return doc


# ===================================================================
# find_users_due_for_review
# ===================================================================
class TestFindUsersDueForReview:
    """Tests the user-filtering logic in find_users_due_for_review."""

    async def test_never_reviewed_user_is_due(self):
        from flashcard.scheduler.scheduler import find_users_due_for_review

        mock_user_service = MagicMock()
        mock_user_service.cols = {"users": MagicMock()}
        mock_user_service.cols["users"].find = MagicMock(
            return_value=_AsyncCursor([
                _make_user_doc(user_id="100", last_reviewed_at=None)
            ])
        )

        result = await find_users_due_for_review(mock_user_service)

        assert len(result) == 1
        assert result[0].user_id == "100"

    async def test_recently_reviewed_user_is_not_due(self):
        from flashcard.scheduler.scheduler import find_users_due_for_review

        # Reviewed 5 minutes ago, interval is 30 min → NOT due
        recent = iso_z(now_utc() - timedelta(minutes=5))
        mock_user_service = MagicMock()
        mock_user_service.cols = {"users": MagicMock()}
        mock_user_service.cols["users"].find = MagicMock(
            return_value=_AsyncCursor([
                _make_user_doc(user_id="200", last_reviewed_at=recent,
                               review_interval_minutes=30)
            ])
        )

        result = await find_users_due_for_review(mock_user_service)

        assert len(result) == 0

    async def test_overdue_user_is_due(self):
        from flashcard.scheduler.scheduler import find_users_due_for_review

        # Reviewed 60 minutes ago, interval is 30 min → due
        old = iso_z(now_utc() - timedelta(minutes=60))
        mock_user_service = MagicMock()
        mock_user_service.cols = {"users": MagicMock()}
        mock_user_service.cols["users"].find = MagicMock(
            return_value=_AsyncCursor([
                _make_user_doc(user_id="300", last_reviewed_at=old,
                               review_interval_minutes=30)
            ])
        )

        result = await find_users_due_for_review(mock_user_service)

        assert len(result) == 1

    async def test_mixed_users_filters_correctly(self):
        from flashcard.scheduler.scheduler import find_users_due_for_review

        recent = iso_z(now_utc() - timedelta(minutes=5))
        old = iso_z(now_utc() - timedelta(minutes=60))

        mock_user_service = MagicMock()
        mock_user_service.cols = {"users": MagicMock()}
        mock_user_service.cols["users"].find = MagicMock(
            return_value=_AsyncCursor([
                _make_user_doc(user_id="due", last_reviewed_at=old),
                _make_user_doc(user_id="not_due", last_reviewed_at=recent),
                _make_user_doc(user_id="new", last_reviewed_at=None),
            ])
        )

        result = await find_users_due_for_review(mock_user_service)
        ids = {u.user_id for u in result}

        assert "due" in ids
        assert "new" in ids
        assert "not_due" not in ids


# ===================================================================
# send_admin_metrics
# ===================================================================
class TestSendAdminMetrics:
    """Tests the admin report formatting."""

    async def test_success_only_report(self):
        from flashcard.scheduler.scheduler import send_admin_metrics

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        # Patch notify_admin_with_trace since it's what the function actually uses
        with patch("flashcard.scheduler.scheduler.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify:
            await send_admin_metrics(
                logger_bot=mock_bot,
                admin_id=12345,
                successful_ids=["u1", "u2"],
                failed_details=[],
                total_time=1.23,
            )

            mock_notify.assert_called_once()
            msg = mock_notify.call_args[0][1]

            assert "Scheduler Cycle Report" in msg
            assert "✅ Successful: 2" in msg
            assert "❌ Failed: 0" in msg
            assert "1.23s" in msg

    async def test_failures_included_in_report(self):
        from flashcard.scheduler.scheduler import send_admin_metrics

        mock_bot = MagicMock()

        with patch("flashcard.scheduler.scheduler.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify:
            await send_admin_metrics(
                logger_bot=mock_bot,
                admin_id=12345,
                successful_ids=["u1"],
                failed_details=[{"user_id": "u2", "error": "Timeout"}],
                total_time=2.5,
            )

            msg = mock_notify.call_args[0][1]
            assert "Failed Users" in msg
            assert "u2" in msg
            assert "Timeout" in msg

    async def test_long_report_splits_messages(self):
        """Reports with many failures should split into multiple messages."""
        from flashcard.scheduler.scheduler import send_admin_metrics

        mock_bot = MagicMock()

        # Create many failures that will trigger message splitting
        failures = [
            {"user_id": f"user_{i}", "error": "x" * 200}
            for i in range(50)
        ]

        with patch("flashcard.scheduler.scheduler.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify:
            await send_admin_metrics(
                logger_bot=mock_bot,
                admin_id=12345,
                successful_ids=[],
                failed_details=failures,
                total_time=5.0,
            )

            # Should have been called multiple times (split messages)
            assert mock_notify.call_count >= 2


class _BreakLoop(Exception):
    """Raised by patched sleep to stop the infinite scheduler loop in tests."""


class TestSchedulerLoopTracing:

    async def test_scheduler_loop_notifies_with_trace_on_loop_error(self):
        from flashcard.scheduler.scheduler import scheduler_loop

        mock_bot = MagicMock()
        mock_logger_bot = MagicMock()
        mock_expression_service = MagicMock()
        mock_user_service = MagicMock()
        mock_consumption_service = MagicMock()
        mock_llm_service = MagicMock()
        mock_trace_logger = MagicMock()

        async def _break_sleep(_seconds):
            raise _BreakLoop()

        with (
            patch("flashcard.scheduler.scheduler._observed_find_users_due_for_review", new_callable=AsyncMock, side_effect=RuntimeError("db down")),
            patch("flashcard.scheduler.scheduler.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify,
            patch("flashcard.services.trace_logger.get_trace_logger", return_value=mock_trace_logger),
            patch("flashcard.scheduler.scheduler.asyncio.sleep", side_effect=_break_sleep),
        ):
            try:
                await scheduler_loop(
                    bot=mock_bot,
                    logger_bot=mock_logger_bot,
                    expression_service=mock_expression_service,
                    user_service=mock_user_service,
                    consumption_service=mock_consumption_service,
                    llm_service=mock_llm_service,
                    admin_id=12345,
                )
            except _BreakLoop:
                pass

        mock_notify.assert_called_once()
        assert "Scheduler Loop Error" in mock_notify.call_args[0][1]
        mock_trace_logger.log_trace_json.assert_called_once()

    async def test_scheduler_loop_records_observed_spans(self):
        from flashcard.scheduler.scheduler import scheduler_loop

        mock_bot = MagicMock()
        mock_logger_bot = MagicMock()
        mock_expression_service = MagicMock()
        mock_user_service = MagicMock()
        mock_consumption_service = MagicMock()
        mock_llm_service = MagicMock()
        mock_trace_logger = MagicMock()

        # One due user to trigger metrics path and observed wrappers.
        old = iso_z(now_utc() - timedelta(minutes=60))
        mock_user_service.cols = {"users": MagicMock()}
        mock_user_service.cols["users"].find = MagicMock(
            return_value=_AsyncCursor([
                _make_user_doc(user_id="u1", last_reviewed_at=old, review_interval_minutes=30)
            ])
        )

        async def _break_sleep(_seconds):
            raise _BreakLoop()

        with (
            patch("flashcard.scheduler.scheduler.send_scheduled_review", new_callable=AsyncMock, return_value=True),
            patch("flashcard.scheduler.scheduler.notify_admin_with_trace", new_callable=AsyncMock),
            patch("flashcard.services.trace_logger.get_trace_logger", return_value=mock_trace_logger),
            patch("flashcard.scheduler.scheduler.asyncio.sleep", side_effect=_break_sleep),
        ):
            try:
                await scheduler_loop(
                    bot=mock_bot,
                    logger_bot=mock_logger_bot,
                    expression_service=mock_expression_service,
                    user_service=mock_user_service,
                    consumption_service=mock_consumption_service,
                    llm_service=mock_llm_service,
                    admin_id=12345,
                )
            except _BreakLoop:
                pass

        trace_json = mock_trace_logger.log_trace_json.call_args[0][0]
        payload = json.loads(trace_json)
        span_names = {s["name"] for s in payload["spans"]}
        assert "scheduler.find_users_due_for_review" in span_names
        assert "scheduler.send_admin_metrics" in span_names
