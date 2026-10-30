"""
Unit tests for flashcard.services.user.UserService

Tests get_user, the settings setters (incl. set_active), advance_onboarding. Review-state writes live in ReviewStateStore.
All use mocked MongoDB.
"""
from unittest.mock import ANY, MagicMock, AsyncMock

import pytest

from flashcard.services.user import UserService
from flashcard.schemas.user import UserDB
from tests.helpers import TEST_LANGUAGE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_service(user_doc=None):
    """Create a UserService with mocked MongoDB."""
    mock_cols = {"users": MagicMock()}
    mock_cols["users"].find_one = AsyncMock(return_value=user_doc)
    mock_cols["users"].update_one = AsyncMock()
    return UserService(users=mock_cols["users"], defaults=TEST_LANGUAGE.user_defaults), mock_cols


# ===================================================================
# get_user
# ===================================================================
class TestGetUser:

    async def test_returns_default_user_db_for_missing_user(self):
        service, _ = _make_service(user_doc=None)

        result = await service.get_user(999)

        assert isinstance(result, UserDB)
        assert result.user_id == 999
        assert result.is_active is True
        assert result.target_level == "A2"  # default

    async def test_returns_validated_model_for_existing_user(self):
        doc = {
            "user_id": "123",
            "is_active": False,
            "primary_language": "fa",
            "target_level": "B1",
            "review_interval_minutes": 60,
        }
        service, _ = _make_service(user_doc=doc)

        result = await service.get_user(123)

        assert isinstance(result, UserDB)
        assert result.user_id == 123
        assert result.is_active is False
        assert result.primary_language == "fa"
        assert result.target_level == "B1"
        assert result.review_interval_minutes == 60


# ===================================================================
# setters: the owner enforces which fields and values can be written
# ===================================================================
class TestSetters:

    @pytest.mark.parametrize("method, value, field", [
        ("set_target_level", "C1", "target_level"),
        ("set_review_interval", 60, "review_interval_minutes"),
        ("set_primary_language", "de", "primary_language"),
        ("set_secondary_language", "fa", "secondary_language"),
        ("set_secondary_language", "none", "secondary_language"),
        ("set_review_mode", "dual", "review_mode"),
        ("set_active", False, "is_active"),
        ("set_active", True, "is_active"),
    ])
    async def test_valid_value_is_written_without_creating_a_user(self, method, value, field):
        service, cols = _make_service()

        await getattr(service, method)(42, value)

        args, kwargs = cols["users"].update_one.call_args
        assert args == ({"user_id": "42"}, {"$set": {field: value}})
        assert not kwargs.get("upsert")

    @pytest.mark.parametrize("method, value", [
        ("set_target_level", "Z9"),
        ("set_target_level", "c1"),
        ("set_review_interval", 14),
        ("set_review_interval", 241),
        ("set_review_interval", 30.0),
        ("set_review_interval", True),
        ("set_primary_language", "none"),
        ("set_primary_language", "English"),
        ("set_secondary_language", "klingon"),
        ("set_review_mode", "triple"),
        ("set_active", "yes"),
        ("set_active", 1),
        ("set_active", None),
    ])
    async def test_invalid_value_is_rejected_without_writing(self, method, value):
        service, cols = _make_service()

        with pytest.raises(ValueError):
            await getattr(service, method)(42, value)
        cols["users"].update_one.assert_not_called()

    @pytest.mark.parametrize("removed", ["update_setting", "toggle_active_status", "get_user_status"])
    def test_removed_methods_stay_removed(self, removed):
        assert not hasattr(UserService, removed)


# ===================================================================
# advance_onboarding
# ===================================================================
class TestAdvanceOnboarding:

    async def test_advances_from_current_step(self):
        """Step 0 → 1 when user is at step 0."""
        service, cols = _make_service()
        cols["users"].update_one = AsyncMock(
            return_value=MagicMock(modified_count=1)
        )

        result = await service.advance_onboarding(123, 0)

        assert result is True
        call_args = cols["users"].update_one.call_args[0]
        assert call_args[0] == {"user_id": "123", "$or": [{"onboarding_step": 0}, {"onboarding_step": {"$exists": False}}]}
        assert call_args[1] == {"$set": {"onboarding_step": 1}}

    async def test_skips_if_already_advanced(self):
        """Returns False if user already past this step."""
        service, cols = _make_service()
        cols["users"].update_one = AsyncMock(
            return_value=MagicMock(modified_count=0)
        )

        result = await service.advance_onboarding(123, 0)

        assert result is False

    async def test_step_1_to_2(self):
        """Step 1 → 2 after first review."""
        service, cols = _make_service()
        cols["users"].update_one = AsyncMock(
            return_value=MagicMock(modified_count=1)
        )

        result = await service.advance_onboarding(123, 1)

        assert result is True
        call_args = cols["users"].update_one.call_args[0]
        assert call_args[0] == {"user_id": "123", "onboarding_step": 1}
        assert call_args[1] == {"$set": {"onboarding_step": 2}}


# ===================================================================
# record_seen
# ===================================================================
class TestRecordSeen:

    async def test_sets_username_and_first_seen(self):
        service, cols = _make_service()
        await service.record_seen(123, "new_handle")

        cols["users"].update_one.assert_called_once_with(
            {"user_id": "123"},
            {"$set": {"username": "new_handle", "last_seen_at": ANY}, "$setOnInsert": {"created_at": ANY}},
            upsert=True
        )
