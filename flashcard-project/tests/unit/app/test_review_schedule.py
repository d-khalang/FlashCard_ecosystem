"""
Unit tests for the review schedule rules: interval, pause, and the legacy-vs-new comparison.
"""
from datetime import timedelta

import pytest

from flashcard.app.review_schedule import PauseComparison, awaiting_answer, compare_pause, interval_elapsed, paused
from flashcard.schemas.user import UserDB
from flashcard.utils.time import iso_z, now_utc

NOW = now_utc()
SENT = iso_z(NOW - timedelta(hours=2))


def _ago(**delta) -> str:
    return iso_z(NOW - timedelta(**delta))


def _user(*, has_pending=False, sent_at=None, last_seen_at=None, **fields) -> UserDB:
    review = None if sent_at is None else {
        "expression_id": "e1", "direction": "forward", "message_id": 1, "sent_at": sent_at}
    return UserDB(user_id="42", has_pending=has_pending, current_review=review, last_seen_at=last_seen_at, **fields)


class TestIntervalElapsed:

    def test_never_reviewed(self):
        assert interval_elapsed(_user(), NOW) is True

    def test_within_interval(self):
        assert interval_elapsed(_user(last_reviewed_at=_ago(minutes=10), review_interval_minutes=30), NOW) is False

    def test_exactly_at_interval(self):
        assert interval_elapsed(_user(last_reviewed_at=_ago(minutes=30), review_interval_minutes=30), NOW) is True


class TestAwaitingAnswer:

    def test_no_current_review(self):
        assert awaiting_answer(_user(last_seen_at=_ago(hours=5))) is False

    def test_never_seen(self):
        assert awaiting_answer(_user(sent_at=SENT)) is True

    def test_seen_before_the_card(self):
        assert awaiting_answer(_user(sent_at=SENT, last_seen_at=_ago(hours=3))) is True

    def test_seen_in_the_same_second_counts_as_before(self):
        """The interaction that triggered a send must not resume reviews."""
        assert awaiting_answer(_user(sent_at=SENT, last_seen_at=SENT)) is True

    def test_seen_after_the_card(self):
        assert awaiting_answer(_user(sent_at=SENT, last_seen_at=_ago(hours=1))) is False


class TestPaused:

    def test_legacy_rule_follows_has_pending(self):
        assert paused(_user(has_pending=True), "legacy") is True
        assert paused(_user(sent_at=SENT), "legacy") is False

    def test_current_review_rule_follows_awaiting_answer(self):
        assert paused(_user(sent_at=SENT), "current_review") is True
        assert paused(_user(has_pending=True), "current_review") is False
        assert paused(_user(has_pending=True, sent_at=SENT, last_seen_at=_ago(hours=1)), "current_review") is False


class TestComparePause:

    @pytest.mark.parametrize("user, expected", [
        (_user(), "agree"),
        (_user(has_pending=True, sent_at=SENT, last_seen_at=_ago(hours=3)), "agree"),
        (_user(has_pending=True, sent_at=SENT, last_seen_at=_ago(hours=1)), "resumed_by_interaction"),
        (_user(has_pending=True), "missing_current_review"),
        (_user(sent_at=SENT, last_seen_at=_ago(hours=3)), "new_pauses"),
        (_user(sent_at=SENT, last_seen_at=_ago(hours=1)), "agree"),
    ])
    def test_categories(self, user, expected):
        assert compare_pause(user) == expected

    def test_report_counts_and_lists_only_mismatches(self):
        report = PauseComparison()
        report.add(_user())
        report.add(_user(has_pending=True))

        assert report.counts == {"agree": 1, "missing_current_review": 1}
        assert report.mismatches == [("42", "missing_current_review")]
