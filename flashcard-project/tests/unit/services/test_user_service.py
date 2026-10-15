"""
Unit tests for flashcard.services.user.UserService

Tests toggle_active_status, get_user_status, get_user, the settings setters,
advance_onboarding. Review-state writes live in ReviewStateStore.
All use mocked MongoDB.
"""
from unittest.mock import MagicMock, AsyncMock

import pytest

from flashcard.services.user import UserService
from flashcard.schemas.user import UserDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_service(user_doc=None):
    """Create a UserService with mocked MongoDB."""
    mock_cols = {"users": MagicMock()}
    mock_cols["users"].find_one = AsyncMock(return_value=user_doc)
    mock_cols["users"].update_one = AsyncMock()
    return UserService(mock_cols), mock_cols


# ===================================================================
# toggle_active_status
# ===================================================================
class TestToggleActiveStatus:

    async def test_active_to_inactive(self):
        service, cols = _make_service(user_doc={"user_id": "123", "is_active": True})

        result = await service.toggle_active_status(123)

        assert result is False
        set_dict = cols["users"].update_one.call_args[0][1]["$set"]
        assert set_dict["is_active"] is False

    async def test_inactive_to_active(self):
        service, cols = _make_service(user_doc={"user_id": "123", "is_active": False})

        result = await service.toggle_active_status(123)

        assert result is True
        set_dict = cols["users"].update_one.call_args[0][1]["$set"]
        assert set_dict["is_active"] is True

    async def test_new_user_defaults_true_toggles_to_false(self):
        """No user doc → default is True → toggles to False."""
        service, cols = _make_service(user_doc=None)

        result = await service.toggle_active_status(123)

        assert result is False

    async def test_missing_is_active_field_defaults_true(self):
        """User doc exists but no is_active field → defaults True → toggles False."""
        service, cols = _make_service(user_doc={"user_id": "123"})

        result = await service.toggle_active_status(123)

        assert result is False

    async def test_double_toggle_returns_to_original(self):
        """Toggling twice should return to the original state."""
        service, cols = _make_service(user_doc={"user_id": "123", "is_active": True})

        first = await service.toggle_active_status(123)
        assert first is False

        # Update mock to reflect the toggle
        cols["users"].find_one = AsyncMock(
            return_value={"user_id": "123", "is_active": False}
        )
        second = await service.toggle_active_status(123)
        assert second is True


# ===================================================================
# get_user_status
# ===================================================================
class TestGetUserStatus:

    async def test_existing_active_user(self):
        service, _ = _make_service(user_doc={"user_id": "123", "is_active": True})
        assert await service.get_user_status(123) is True

    async def test_existing_inactive_user(self):
        service, _ = _make_service(user_doc={"user_id": "123", "is_active": False})
        assert await service.get_user_status(123) is False

    async def test_missing_user_defaults_to_true(self):
        service, _ = _make_service(user_doc=None)
        assert await service.get_user_status(999) is True


# ===================================================================
# get_user
# ===================================================================
class TestGetUser:

    async def test_returns_default_user_db_for_missing_user(self):
        service, _ = _make_service(user_doc=None)

        result = await service.get_user(999)

        assert isinstance(result, UserDB)
        assert result.user_id == "999"
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
        assert result.user_id == "123"
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
    ])
    async def test_invalid_value_is_rejected_without_writing(self, method, value):
        service, cols = _make_service()

        with pytest.raises(ValueError):
            await getattr(service, method)(42, value)
        cols["users"].update_one.assert_not_called()

    def test_there_is_no_generic_field_writer(self):
        assert not hasattr(UserService, "update_setting")


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
