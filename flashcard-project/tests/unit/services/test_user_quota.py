import pytest
from datetime import timedelta
from unittest.mock import MagicMock, AsyncMock, ANY
from flashcard.services.user import UserService
from flashcard.schemas.user import UserDB, UserTier
from flashcard.utils.time import now_utc, iso_z

def _make_service():
    mock_cols = {"users": MagicMock(), "consumption": MagicMock()}
    # update_one is often awaited
    mock_cols["users"].update_one = AsyncMock()
    return UserService(mock_cols), mock_cols

class TestUserServiceQuota:

    def test_get_effective_limits_admin(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.admin)
        limits = service._get_effective_limits(user)
        assert limits["cards"] == 999
        assert limits["stories"] == 99

    def test_get_effective_limits_plus(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.plus)
        limits = service._get_effective_limits(user)
        assert limits["cards"] == 50
        assert limits["stories"] == 10

    def test_get_effective_limits_digi(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.digi)
        limits = service._get_effective_limits(user)
        assert limits["cards"] == 40
        assert limits["stories"] == 3

    def test_get_effective_limits_normal_trial_new_user(self):
        """User has no created_at (hasn't saved anything yet) -> should get plus limits."""
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.normal, created_at=None)
        limits = service._get_effective_limits(user)
        assert limits["cards"] == 50
        assert limits["stories"] == 10

    def test_get_effective_limits_normal_trial(self):
        service, _ = _make_service()
        # Created 5 days ago (within 14 days)
        created_at = iso_z(now_utc() - timedelta(days=5))
        user = UserDB(user_id="1", tier=UserTier.normal, created_at=created_at)
        limits = service._get_effective_limits(user)
        # Should get 'plus' limits
        assert limits["cards"] == 50
        assert limits["stories"] == 10

    def test_get_effective_limits_normal_expired(self):
        service, _ = _make_service()
        # Created 20 days ago (past 14 days)
        created_at = iso_z(now_utc() - timedelta(days=20))
        user = UserDB(user_id="1", tier=UserTier.normal, created_at=created_at)
        limits = service._get_effective_limits(user)
        # Should get 'normal' limits (2 cards, as updated by user)
        assert limits["cards"] == 10
        assert limits["stories"] == 2

    def test_can_generate_card_admin_always_true(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.admin)
        # Even if consumption is huge
        user.consumption.system_api.cards_generated = 9999
        assert service.can_generate_card(user) is True

    def test_can_generate_card_own_key_always_true(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.normal)
        user.consumption.system_api.cards_generated = 9999
        # Uses own key -> unlimited
        assert service.can_generate_card(user, uses_own_key=True) is True

    def test_can_generate_card_enforces_limit(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.plus)
        
        # Below limit (49 < 50)
        user.consumption.system_api.cards_generated = 49
        assert service.can_generate_card(user) is True
        
        # At limit (50 == 50)
        user.consumption.system_api.cards_generated = 50
        assert service.can_generate_card(user) is False

    def test_can_generate_story_enforces_limit(self):
        service, _ = _make_service()
        user = UserDB(user_id="1", tier=UserTier.digi)
        
        # Below limit (2 < 3)
        user.consumption.system_api.stories_generated = 2
        assert service.can_generate_story(user) is True
        
        # At limit (3 == 3)
        user.consumption.system_api.stories_generated = 3
        assert service.can_generate_story(user) is False

    @pytest.mark.asyncio
    async def test_update_username(self):
        service, cols = _make_service()
        await service.update_username("123", "new_handle")
        
        cols["users"].update_one.assert_called_once_with(
            {"user_id": "123"},
            {"$set": {"username": "new_handle"}, "$setOnInsert": {"created_at": ANY}},
            upsert=True
        )
