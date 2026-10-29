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

import pytest

from flashcard.schemas.user import UserDB
from flashcard.services.user import UserService
from flashcard.utils.time import now_utc, iso_z
from tests.helpers import AsyncCursorMock as _AsyncCursor
from tests.helpers import TEST_I18N, TEST_LANGUAGE


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

        mock_user_service = UserService(users=MagicMock(), defaults=TEST_LANGUAGE.user_defaults)
        mock_user_service.users.find = MagicMock(
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
        mock_user_service = UserService(users=MagicMock(), defaults=TEST_LANGUAGE.user_defaults)
        mock_user_service.users.find = MagicMock(
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
        mock_user_service = UserService(users=MagicMock(), defaults=TEST_LANGUAGE.user_defaults)
        mock_user_service.users.find = MagicMock(
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

        mock_user_service = UserService(users=MagicMock(), defaults=TEST_LANGUAGE.user_defaults)
        mock_user_service.users.find = MagicMock(
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
        mock_user_service = MagicMock()
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
                    user_service=mock_user_service,
                    review_use_cases=MagicMock(),
                    language=TEST_LANGUAGE,
                    i18n=TEST_I18N,
                    admin_id=12345,
                    check_interval_seconds=600,
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
        mock_user_service = UserService(users=MagicMock(), defaults=TEST_LANGUAGE.user_defaults)
        mock_trace_logger = MagicMock()

        # One due user to trigger metrics path and observed wrappers.
        old = iso_z(now_utc() - timedelta(minutes=60))
        mock_user_service.users.find = MagicMock(
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
                    user_service=mock_user_service,
                    review_use_cases=MagicMock(),
                    language=TEST_LANGUAGE,
                    i18n=TEST_I18N,
                    admin_id=12345,
                    check_interval_seconds=600,
                )
            except _BreakLoop:
                pass

        trace_json = mock_trace_logger.log_trace_json.call_args[0][0]
        payload = json.loads(trace_json)
        span_names = {s["name"] for s in payload["spans"]}
        assert "scheduler.find_users_due_for_review" in span_names
        assert "scheduler.send_admin_metrics" in span_names


# ===================================================================
# compare_pause_rules (review-state shadow compare)
# ===================================================================
class TestComparePauseRules:

    def _service(self, *users):
        from tests.integration.helpers import make_cols
        return UserService(users=make_cols(users=list(users))["users"], defaults=TEST_LANGUAGE.user_defaults)

    def _review(self, sent_at):
        return {"expression_id": "e1", "direction": "forward", "message_id": 1, "sent_at": sent_at}

    async def test_counts_only_users_either_rule_could_pause(self):
        from flashcard.scheduler.scheduler import compare_pause_rules
        sent = iso_z(now_utc() - timedelta(hours=2))
        service = self._service(
            _make_user_doc(user_id="free"),
            _make_user_doc(user_id="both", has_pending=True, current_review=self._review(sent)),
            _make_user_doc(user_id="resumed", has_pending=True, current_review=self._review(sent),
                           last_seen_at=iso_z(now_utc())),
            _make_user_doc(user_id="gap", has_pending=True),
            _make_user_doc(user_id="inactive", is_active=False, has_pending=True),
        )

        report = await compare_pause_rules(service)

        assert report.counts == {"agree": 1, "resumed_by_interaction": 1, "missing_current_review": 1}
        assert sorted(report.mismatches) == [("gap", "missing_current_review"), ("resumed", "resumed_by_interaction")]

    async def test_compare_failure_never_breaks_the_cycle(self, caplog):
        from flashcard.scheduler.scheduler import _log_pause_comparison
        service = MagicMock()
        service.active_users_possibly_paused = AsyncMock(side_effect=RuntimeError("mongo down"))

        await _log_pause_comparison(service)

        assert "shadow compare failed" in caplog.text


# ===================================================================
# find_users_due_for_review with the current_review pause rule
# ===================================================================
class TestFindUsersDueCurrentReviewRule:

    def _service(self, *users):
        from tests.integration.helpers import make_cols
        return UserService(users=make_cols(users=list(users))["users"], defaults=TEST_LANGUAGE.user_defaults)

    def _review(self, hours_ago):
        return {"expression_id": "e1", "direction": "forward", "message_id": 1,
                "sent_at": iso_z(now_utc() - timedelta(hours=hours_ago))}

    async def _due(self, service, rule):
        from flashcard.scheduler.scheduler import find_users_due_for_review
        return sorted(user.user_id for user in await find_users_due_for_review(service, rule))

    async def test_rules_differ_only_on_the_pause(self):
        seen_after = iso_z(now_utc() - timedelta(hours=1))
        service = self._service(
            _make_user_doc(user_id="free"),
            _make_user_doc(user_id="waiting", has_pending=True, current_review=self._review(2)),
            _make_user_doc(user_id="resumed", has_pending=True, current_review=self._review(2),
                           last_seen_at=seen_after),
            _make_user_doc(user_id="stuck", has_pending=True),
        )

        assert await self._due(service, "legacy") == ["free"]
        assert await self._due(service, "current_review") == ["free", "resumed", "stuck"]

    async def test_interval_and_active_still_apply(self):
        service = self._service(
            _make_user_doc(user_id="recent", last_reviewed_at=iso_z(now_utc() - timedelta(minutes=5))),
            _make_user_doc(user_id="inactive", is_active=False),
        )

        assert await self._due(service, "current_review") == []


class TestBadStoredReviewMode:

    async def test_unknown_review_mode_does_not_break_the_tick(self):
        """One bad stored value must not stop reviews for every user."""
        from flashcard.scheduler.scheduler import find_users_due_for_review
        from tests.integration.helpers import make_cols
        cols = make_cols(users=[_make_user_doc(user_id="bad", review_mode="weird"), _make_user_doc(user_id="ok")])
        service = UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults)

        due = await find_users_due_for_review(service)

        assert sorted(user.user_id for user in due) == ["bad", "ok"]


# ===================================================================
# Per-user isolation: one unreadable user document never stops a tick
# ===================================================================
class TestPerUserIsolation:

    def _service(self, *users):
        from tests.integration.helpers import make_cols
        return UserService(users=make_cols(users=list(users))["users"], defaults=TEST_LANGUAGE.user_defaults)

    @pytest.mark.parametrize("bad_fields", [
        {"target_level": "Z9"},                       # schema validation error
        {"review_interval_minutes": "often"},          # wrong type
        {"last_reviewed_at": "2000-13-45T00:00:00Z"},  # passes the DB prefilter, fails parsing
        {"current_review": {"expression_id": "e1"}},   # incomplete embedded review
    ])
    async def test_bad_user_is_skipped_and_reported(self, bad_fields):
        from flashcard.scheduler.scheduler import find_users_due_for_review
        service = self._service(_make_user_doc(user_id="bad", **bad_fields), _make_user_doc(user_id="ok"))
        skipped = []

        due = await find_users_due_for_review(service, skipped=skipped)

        assert [user.user_id for user in due] == ["ok"]
        assert [entry["user_id"] for entry in skipped] == ["bad"]
        assert skipped[0]["error"].startswith("Unreadable user document")

    async def test_naive_date_under_the_new_rule_is_skipped_not_fatal(self):
        """A naive sent_at minus an aware last_seen_at raises TypeError."""
        from flashcard.scheduler.scheduler import find_users_due_for_review
        review = {"expression_id": "e1", "direction": "forward", "message_id": 1, "sent_at": "2026-10-01T10:00:00"}
        service = self._service(
            _make_user_doc(user_id="bad", current_review=review, last_seen_at="2026-10-02T10:00:00Z"),
            _make_user_doc(user_id="ok"),
        )
        skipped = []

        due = await find_users_due_for_review(service, "current_review", skipped)

        assert [user.user_id for user in due] == ["ok"]
        assert [entry["user_id"] for entry in skipped] == ["bad"]

    async def test_without_a_collector_bad_users_are_only_logged(self, caplog):
        from flashcard.scheduler.scheduler import find_users_due_for_review
        service = self._service(_make_user_doc(user_id="bad", target_level="Z9"), _make_user_doc(user_id="ok"))

        due = await find_users_due_for_review(service)

        assert [user.user_id for user in due] == ["ok"]
        assert "Skipping user bad" in caplog.text

    async def test_shadow_compare_counts_unreadable_users(self):
        from flashcard.scheduler.scheduler import compare_pause_rules
        service = self._service(_make_user_doc(user_id="bad", has_pending=True, target_level="Z9"),
                                _make_user_doc(user_id="ok", has_pending=True))

        report = await compare_pause_rules(service)

        assert report.counts == {"unreadable": 1, "missing_current_review": 1}

    async def test_skipped_users_reach_the_admin_report(self):
        from flashcard.scheduler.scheduler import scheduler_loop

        async def find_users(user_service, pause_rule, skipped):
            skipped.append({"user_id": "bad", "error": "Unreadable user document: ValidationError"})
            return []

        async def _break_sleep(_seconds):
            raise _BreakLoop()

        with (
            patch("flashcard.scheduler.scheduler._observed_find_users_due_for_review", side_effect=find_users),
            patch("flashcard.scheduler.scheduler._log_pause_comparison", new_callable=AsyncMock),
            patch("flashcard.scheduler.scheduler._observed_send_admin_metrics", new_callable=AsyncMock) as metrics,
            patch("flashcard.scheduler.scheduler.asyncio.sleep", side_effect=_break_sleep),
        ):
            try:
                await scheduler_loop(bot=MagicMock(), logger_bot=MagicMock(), user_service=MagicMock(),
                                     review_use_cases=MagicMock(), language=TEST_LANGUAGE, i18n=TEST_I18N, admin_id=12345,
                                     check_interval_seconds=600)
            except _BreakLoop:
                pass

        assert metrics.call_args.kwargs["failed_details"] == [
            {"user_id": "bad", "error": "Unreadable user document: ValidationError"}]
