"""
Guard: the bot's review path is unchanged by the Mini App work.

mark_sent and grade write what they always wrote (a Telegram message id, the legacy pause flag,
no undo data), and `awaiting_answer` still decides on `last_seen_at` for positive message ids.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

from flashcard.app.review import Graded, ReviewReady, ReviewUseCases
from flashcard.app.review_schedule import awaiting_answer
from flashcard.schemas.expression import CardSettings
from flashcard.schemas.user import CurrentReview
from tests.helpers import make_quota, make_user
from tests.integration.helpers import make_cols, make_services
from tests.integration.study_helpers import make_card

SENT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
SETTINGS = CardSettings(level="A2", primary_language="en", secondary_language=None)


@pytest.fixture
def env():
    cols = make_cols(users=[{"user_id": "42", "has_pending": False}],
                     expressions=[{"_id": ObjectId(), "user_id": "42", "value": "andare",
                                   "created_at": SENT, "status": "active",
                                   "grade_undo": {"delivery_id": -5}}])
    services = make_services(cols)
    consumption = MagicMock()
    consumption.increment = AsyncMock()
    use_cases = ReviewUseCases(
        expression_service=services["expression_service"], user_service=services["user_service"],
        quota=make_quota(consumption), llm_service=MagicMock(), review_state=services["review_state"])
    expression = cols["expression"].docs[0]
    return use_cases, cols, str(expression["_id"]), consumption


def _ready(expression_id, quota=None):
    from flashcard.app.quota import Allowed
    return ReviewReady(expression_id=expression_id, value="andare", direction="forward", card=make_card(),
                       settings=SETTINGS, quota=Allowed(uses_own_key=False, credits=2) if quota is None else quota)


async def test_mark_sent_still_stores_the_message_id_and_sets_the_legacy_flag(env):
    use_cases, cols, expression_id, consumption = env

    await use_cases.mark_sent(42, _ready(expression_id), 555)

    expression = cols["expression"].docs[0]
    assert expression["pending_message_id"] == 555
    assert expression["last_sent_at"] and expression["last_activity_at"]
    assert expression["last_card"]["card"]["norm"] == "andare"
    user = cols["users"].docs[0]
    assert user["has_pending"] is True
    assert user["current_review"]["message_id"] == 555 and user["current_review"]["direction"] == "forward"
    consumption.increment.assert_awaited_once()


async def test_grade_still_grades_once_per_message_and_leaves_no_undo_data(env):
    use_cases, cols, expression_id, _ = env
    await use_cases.mark_sent(42, _ready(expression_id), 555)

    first = await use_cases.grade(42, expression_id, 4, "forward", message_id=555)
    second = await use_cases.grade(42, expression_id, 4, "forward", message_id=555)

    assert first == Graded() and second.__class__.__name__ == "NotPending"
    expression = cols["expression"].docs[0]
    assert expression["reps"] == 1 and expression["pending_message_id"] is None
    assert "grade_undo" not in expression  # a bot grade unsets any app snapshot
    user = cols["users"].docs[0]
    assert user["has_pending"] is False and user["last_reviewed_at"]
    assert "current_review" not in user and "last_app_grade" not in user


async def test_a_bot_grade_of_a_different_message_id_is_still_refused(env):
    use_cases, cols, expression_id, _ = env
    await use_cases.mark_sent(42, _ready(expression_id), 555)

    result = await use_cases.grade(42, expression_id, 4, "forward", message_id=556)

    assert result.__class__.__name__ == "NotPending"
    assert cols["expression"].docs[0]["pending_message_id"] == 555


def _user(message_id, *, last_seen):
    return make_user(user_id=42, last_seen_at=last_seen, current_review=CurrentReview(
        expression_id="e", direction="forward", message_id=message_id, sent_at=SENT))


class TestAwaitingAnswer:

    @pytest.mark.parametrize("message_id", [1, 555, 2**31])
    def test_unchanged_for_telegram_message_ids(self, message_id):
        assert awaiting_answer(_user(message_id, last_seen=None)) is True
        assert awaiting_answer(_user(message_id, last_seen=SENT)) is True
        assert awaiting_answer(_user(message_id, last_seen=SENT - timedelta(hours=1))) is True
        assert awaiting_answer(_user(message_id, last_seen=SENT + timedelta(seconds=1))) is False

    @pytest.mark.parametrize("message_id", [-1, -777, -(2**53 - 1)])
    def test_an_app_card_never_holds_back_reminders(self, message_id):
        for last_seen in (None, SENT, SENT - timedelta(hours=1), SENT + timedelta(hours=1)):
            assert awaiting_answer(_user(message_id, last_seen=last_seen)) is False

    def test_no_current_review_is_not_awaiting(self):
        assert awaiting_answer(make_user(user_id=42)) is False

    def test_in_app_means_a_negative_delivery_id(self):
        base = dict(expression_id="e", direction="forward", sent_at=SENT)
        assert CurrentReview(message_id=-1, **base).in_app is True
        assert CurrentReview(message_id=1, **base).in_app is False
