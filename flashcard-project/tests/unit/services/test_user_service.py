"""
Unit tests for flashcard.services.user.UserService

Tests all 5 methods: update_user_last_push, toggle_active_status,
get_user_status, get_user, update_setting.
All use mocked MongoDB.
"""
from unittest.mock import MagicMock, AsyncMock

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
# update_user_last_push
# ===================================================================
class TestUpdateUserLastPush:

    async def test_sets_last_push_and_has_pending(self):
        service, cols = _make_service()

        await service.update_user_last_push(123)

        cols["users"].update_one.assert_called_once()
        call_args = cols["users"].update_one.call_args
        assert call_args[0][0] == {"user_id": "123"}
        set_dict = call_args[0][1]["$set"]
        assert "last_push_at" in set_dict
        assert set_dict["has_pending"] is True

    async def test_upserts_for_new_user(self):
        service, cols = _make_service()

        await service.update_user_last_push(999)

        call_kwargs = cols["users"].update_one.call_args[1]
        assert call_kwargs.get("upsert") is True


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
# update_setting
# ===================================================================
class TestUpdateSetting:

    async def test_updates_arbitrary_field(self):
        service, cols = _make_service()

        await service.update_setting(123, "primary_language", "de")

        call_args = cols["users"].update_one.call_args[0]
        assert call_args[0] == {"user_id": "123"}
        assert call_args[1] == {"$set": {"primary_language": "de"}}

    async def test_upserts_for_new_user(self):
        service, cols = _make_service()

        await service.update_setting(999, "target_level", "C1")

        call_kwargs = cols["users"].update_one.call_args[1]
        assert call_kwargs.get("upsert") is True

    async def test_converts_int_user_id_to_string(self):
        """Integer user_id should be converted to string in the query."""
        service, cols = _make_service()

        await service.update_setting(42, "target_level", "B2")

        call_args = cols["users"].update_one.call_args[0]
        assert call_args[0]["user_id"] == "42"  # string, not int
