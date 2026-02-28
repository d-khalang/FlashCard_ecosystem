"""
Unit tests for ExpressionService — P0 critical methods.

Tests the remaining untested methods with mocked MongoDB:
  - get_review_candidate: cooldown filtering, priority selection, dual mode
  - grade_expression: forward + reverse stat updates, validation
  - add_expressions_bulk: duplicate filtering, bulk insert
  - update_expression_sent: timestamp + pending message tracking

These complement the existing test_expression_service.py (add/get basics).
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from bson import ObjectId

from flashcard.services.expression import ExpressionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_service(expressions=None, users=None):
    """Create an ExpressionService with mocked MongoDB collections."""
    mock_cols = {
        "expression": MagicMock(),
        "users": MagicMock(),
    }
    mock_cols["expression"].find_one = AsyncMock(return_value=None)
    mock_cols["expression"].insert_one = AsyncMock()
    mock_cols["expression"].insert_many = AsyncMock()
    mock_cols["expression"].update_one = AsyncMock()
    mock_cols["users"].find_one = AsyncMock(return_value=users)
    mock_cols["users"].update_one = AsyncMock()
    return ExpressionService(mock_cols), mock_cols


# ===================================================================
# add_expression (single)
# ===================================================================
class TestAddExpression:
    """Tests for adding a single expression."""

    async def test_add_new_expression(self):
        """New expression → inserts doc, updates user, returns True."""
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value=None)

        result = await service.add_expression(12345, "test_expression")

        assert result is True
        cols["expression"].find_one.assert_called_once()
        cols["expression"].insert_one.assert_called_once()

        # Verify inserted document structure
        inserted = cols["expression"].insert_one.call_args[0][0]
        assert inserted["user_id"] == "12345"
        assert inserted["value"] == "test_expression"
        assert inserted["reps"] == 0
        assert inserted["status"] == "active"

        # Verify user update
        cols["users"].update_one.assert_called_once()
        user_set = cols["users"].update_one.call_args[0][1]["$set"]
        assert user_set["has_pending"] is False

    async def test_add_duplicate_returns_false(self):
        """Duplicate expression → no insert, returns False."""
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value={"_id": "existing"})

        result = await service.add_expression(12345, "Duplicate")

        assert result is False
        cols["expression"].insert_one.assert_not_called()
        cols["users"].update_one.assert_not_called()


# ===================================================================
# get_all_expressions
# ===================================================================
class TestGetAllExpressions:
    """Tests for retrieving all expressions."""

    async def test_returns_distinct_values(self):
        service, cols = _make_service()
        expected = ["exp1", "exp2"]
        cols["expression"].distinct = AsyncMock(return_value=expected)

        result = await service.get_all_expressions(999)

        assert result == expected
        cols["expression"].distinct.assert_called_once_with(
            "value", {"user_id": "999"}
        )



def _make_expression_doc(**overrides):
    """Create a realistic expression document."""
    base = {
        "_id": ObjectId(),
        "user_id": "123",
        "value": "parlare",
        "created_at": "2026-01-01T00:00:00Z",
        "last_activity_at": "2026-01-01T00:00:00Z",  # old enough to pass cooldown
        "last_interaction_at": None,
        "reps": 0,
        "lapses": 0,
        "success_streak": 0,
        "ewma_grade": 0.0,
        "last_grade": 0,
        "reverse_stats": None,
        "pending_message_id": None,
        "status": "active",
    }
    base.update(overrides)
    return base


class _AsyncIterator:
    """Wraps a list as an async iterator to simulate MongoDB cursor."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


# ===================================================================
# get_review_candidate
# ===================================================================
class TestGetReviewCandidate:
    """Tests for selecting the best card to review."""

    async def test_returns_none_when_no_expressions(self):
        service, cols = _make_service()
        cols["expression"].find = MagicMock(return_value=_AsyncIterator([]))

        result = await service.get_review_candidate("123")
        assert result is None

    async def test_returns_best_candidate_by_priority(self):
        """With multiple candidates, returns the one with highest priority."""
        service, cols = _make_service()

        # Card A: reviewed recently (lower priority)
        card_a = _make_expression_doc(
            value="casa", reps=5, ewma_grade=4.0, success_streak=5
        )
        # Card B: never reviewed (higher priority due to novelty + difficulty)
        card_b = _make_expression_doc(
            value="difficile", reps=0, ewma_grade=0.0, success_streak=0
        )
        cols["expression"].find = MagicMock(
            return_value=_AsyncIterator([card_a, card_b])
        )

        result = await service.get_review_candidate("123")

        assert result is not None
        assert result["doc"]["value"] == "difficile"
        assert result["direction"] == "forward"

    async def test_returns_direction_key(self):
        """Result dict must include a 'direction' key."""
        service, cols = _make_service()
        doc = _make_expression_doc()
        cols["expression"].find = MagicMock(return_value=_AsyncIterator([doc]))

        result = await service.get_review_candidate("123")

        assert "doc" in result
        assert "direction" in result

    async def test_dual_mode_can_select_reverse(self):
        """In dual mode, reverse direction can win if its priority is higher."""
        service, cols = _make_service(
            users={"user_id": "123", "review_mode": "dual"}
        )

        # Card with strong forward stats but weak reverse stats
        doc = _make_expression_doc(
            reps=10,
            ewma_grade=4.5,
            success_streak=8,  # strong forward → low priority
            reverse_stats={
                "reps": 0,
                "ewma_grade": 0.0,
                "success_streak": 0,
                "lapses": 0,
            },  # weak reverse → high priority
        )
        cols["expression"].find = MagicMock(return_value=_AsyncIterator([doc]))

        result = await service.get_review_candidate("123")

        assert result is not None
        assert result["direction"] == "reverse"

    async def test_standard_mode_never_returns_reverse(self):
        """In standard mode, direction should always be 'forward'."""
        service, cols = _make_service(
            users={"user_id": "123", "review_mode": "standard"}
        )

        doc = _make_expression_doc(
            reverse_stats={"reps": 0, "ewma_grade": 0.0, "success_streak": 0, "lapses": 0}
        )
        cols["expression"].find = MagicMock(return_value=_AsyncIterator([doc]))

        result = await service.get_review_candidate("123")

        assert result["direction"] == "forward"


# ===================================================================
# grade_expression
# ===================================================================
class TestGradeExpression:
    """Tests for grading a flashcard after review."""

    async def test_invalid_grade_returns_none(self):
        """Grade outside 0-5 should be rejected."""
        service, cols = _make_service()

        result = await service.grade_expression("123", str(ObjectId()), grade=6)
        assert result is None

        result = await service.grade_expression("123", str(ObjectId()), grade=-1)
        assert result is None

        # No DB writes should happen
        cols["expression"].update_one.assert_not_called()

    async def test_missing_expression_returns_none(self):
        """Expression not found in DB → returns None."""
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value=None)

        result = await service.grade_expression("123", str(ObjectId()), grade=4)
        assert result is None
        cols["expression"].update_one.assert_not_called()

    async def test_forward_grade_updates_root_stats(self):
        """Forward grading should update root-level stats."""
        doc = _make_expression_doc()
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value=doc)

        result = await service.grade_expression(
            "123", str(doc["_id"]), grade=4, direction="forward"
        )

        assert result is not None
        # Check expression was updated
        cols["expression"].update_one.assert_called_once()
        update_args = cols["expression"].update_one.call_args[0]
        set_dict = update_args[1]["$set"]

        # Forward stats at root level
        assert "reps" in set_dict
        assert "last_activity_at" in set_dict
        assert "pending_message_id" in set_dict  # cleared
        assert set_dict["pending_message_id"] is None

    async def test_reverse_grade_updates_nested_stats(self):
        """Reverse grading should update under reverse_stats."""
        doc = _make_expression_doc(
            reverse_stats={"reps": 2, "ewma_grade": 3.0, "success_streak": 2, "lapses": 0, "last_grade": 3}
        )
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value=doc)

        await service.grade_expression(
            "123", str(doc["_id"]), grade=5, direction="reverse"
        )

        update_args = cols["expression"].update_one.call_args[0]
        set_dict = update_args[1]["$set"]

        # Should use dot notation for existing reverse_stats
        assert any(k.startswith("reverse_stats.") for k in set_dict)

    async def test_reverse_grade_creates_reverse_stats_if_none(self):
        """If reverse_stats is None, should set the whole object."""
        doc = _make_expression_doc(reverse_stats=None)
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value=doc)

        await service.grade_expression(
            "123", str(doc["_id"]), grade=3, direction="reverse"
        )

        update_args = cols["expression"].update_one.call_args[0]
        set_dict = update_args[1]["$set"]

        # Should set the whole reverse_stats object (not dot notation)
        assert "reverse_stats" in set_dict
        assert isinstance(set_dict["reverse_stats"], dict)

    async def test_grade_updates_user_has_pending(self):
        """After grading, user's has_pending should be set to False."""
        doc = _make_expression_doc()
        service, cols = _make_service()
        cols["expression"].find_one = AsyncMock(return_value=doc)

        await service.grade_expression("123", str(doc["_id"]), grade=4)

        cols["users"].update_one.assert_called_once()
        user_update = cols["users"].update_one.call_args[0][1]["$set"]
        assert user_update["has_pending"] is False
        assert "last_reviewed_at" in user_update


# ===================================================================
# add_expressions_bulk
# ===================================================================
class TestAddExpressionsBulk:
    """Tests for bulk importing expressions."""

    async def test_empty_list_returns_empty(self):
        service, cols = _make_service()
        result = await service.add_expressions_bulk("123", [])
        assert result == []
        cols["expression"].insert_many.assert_not_called()

    async def test_all_new_items_inserted(self):
        """No duplicates in DB → all items inserted."""
        service, cols = _make_service()
        cols["expression"].find = MagicMock(return_value=_AsyncIterator([]))

        result = await service.add_expressions_bulk("123", ["casa", "gatto", "cane"])

        assert len(result) == 3
        cols["expression"].insert_many.assert_called_once()
        inserted = cols["expression"].insert_many.call_args[0][0]
        assert len(inserted) == 3

    async def test_duplicates_in_db_are_skipped(self):
        """Items already in DB should not be re-inserted."""
        service, cols = _make_service()
        # "casa" already exists in DB
        cols["expression"].find = MagicMock(
            return_value=_AsyncIterator([{"value": "casa"}])
        )

        result = await service.add_expressions_bulk("123", ["casa", "gatto"])

        assert result == ["gatto"]
        inserted = cols["expression"].insert_many.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0]["value"] == "gatto"

    async def test_all_duplicates_returns_empty(self):
        """All items already exist → empty list, no insert."""
        service, cols = _make_service()
        cols["expression"].find = MagicMock(
            return_value=_AsyncIterator([{"value": "casa"}, {"value": "gatto"}])
        )

        result = await service.add_expressions_bulk("123", ["casa", "gatto"])

        assert result == []
        cols["expression"].insert_many.assert_not_called()

    async def test_updates_user_after_bulk_insert(self):
        """User's last_push_at should be updated after successful bulk insert."""
        service, cols = _make_service()
        cols["expression"].find = MagicMock(return_value=_AsyncIterator([]))

        await service.add_expressions_bulk("123", ["nuova"])

        cols["users"].update_one.assert_called_once()
        user_update = cols["users"].update_one.call_args[0][1]["$set"]
        assert "last_push_at" in user_update
        assert user_update["has_pending"] is False


# ===================================================================
# update_expression_sent
# ===================================================================
class TestUpdateExpressionSent:
    """Tests for marking an expression as sent."""

    async def test_sets_sent_timestamp_and_message_id(self):
        service, cols = _make_service()
        expr_id = str(ObjectId())
        msg_id = 42

        await service.update_expression_sent(expr_id, msg_id)

        cols["expression"].update_one.assert_called_once()
        call_args = cols["expression"].update_one.call_args[0]

        # Check filter
        assert call_args[0]["_id"] == ObjectId(expr_id)

        # Check updates
        set_dict = call_args[1]["$set"]
        assert "last_sent_at" in set_dict
        assert "last_activity_at" in set_dict
        assert set_dict["pending_message_id"] == 42
