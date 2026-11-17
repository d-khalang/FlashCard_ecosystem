"""
Smaller pieces added for the Mini App: usage numbers, batched settings, and the setting for access.
"""

import pytest
from pydantic import ValidationError

from flashcard.app.quota import QuotaPolicy
from flashcard.app.settings import SettingsUseCases
from flashcard.schemas.user import UserAPIConfig, UserTier
from flashcard.services.consumption import ConsumptionService
from flashcard.services.user import UserService
from flashcard.settings import Settings, get_setting
from tests.helpers import TEST_LANGUAGE, TEST_LIMITS, make_user
from tests.integration.helpers import make_cols


def _policy():
    return QuotaPolicy(ConsumptionService(users=None), TEST_LIMITS)


def _consumption(system=0, own=0):
    from flashcard.utils.time import now_utc
    return {"consumption_date": now_utc().date().isoformat(),
            "system_api": {"credits_used": system}, "user_api": {"credits_used": own}}


class TestUsage:

    def test_normal_user_after_the_trial(self):
        from datetime import timedelta
        from flashcard.utils.time import now_utc
        user = make_user(user_id=1, created_at=now_utc() - timedelta(days=30), consumption=_consumption(system=4))

        usage = _policy().usage(user, "cards")

        assert (usage.used, usage.limit) == (4, 20)

    def test_own_key_and_admin_are_not_limited(self):
        own = make_user(user_id=1, api_config=UserAPIConfig(api_key="k"), consumption=_consumption(system=3, own=7))
        admin = make_user(user_id=2, tier=UserTier.admin, consumption=_consumption(system=5))

        assert (_policy().usage(own, "cards").used, _policy().usage(own, "cards").limit) == (7, None)
        assert (_policy().usage(admin, "cards").used, _policy().usage(admin, "cards").limit) == (5, None)

    def test_yesterdays_count_does_not_show(self):
        user = make_user(user_id=1, consumption={"consumption_date": "2000-01-01",
                                                 "system_api": {"credits_used": 9}})

        assert _policy().usage(user, "cards").used == 0


class TestSettingsUpdate:

    def _use_cases(self):
        cols = make_cols(users=[{"user_id": "7"}])
        return SettingsUseCases(UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults)), cols["users"]

    async def test_applies_every_change_and_returns_the_user(self):
        use_cases, users = self._use_cases()

        user = await use_cases.update(7, {"target_level": "C1", "primary_language": "Persian",
                                          "secondary_language": "de", "review_mode": "dual",
                                          "review_interval_minutes": 120, "is_active": False})

        assert (user.target_level, user.primary_language, user.secondary_language) == ("C1", "fa", "de")
        assert (user.review_mode, user.review_interval_minutes, user.is_active) == ("dual", 120, False)

    async def test_null_secondary_language_turns_it_off(self):
        use_cases, users = self._use_cases()
        users.docs[0]["secondary_language"] = "de"

        assert (await use_cases.update(7, {"secondary_language": None})).secondary_language is None

    @pytest.mark.parametrize("changes", [
        {"target_level": "B1", "review_interval_minutes": 3},
        {"target_level": "B1", "primary_language": "klingon"},
        {"is_active": "yes"}, {"review_mode": "x"}, {"tier": "admin"}, {"secondary_language": 5},
    ])
    async def test_a_bad_value_changes_nothing(self, changes):
        use_cases, users = self._use_cases()

        with pytest.raises(ValueError):
            await use_cases.update(7, changes)

        assert users.docs[0] == {"user_id": "7"}


class TestAccessSetting:

    def _settings(self, **fields):
        base = get_setting().model_dump()
        return Settings(**{**base, **fields})

    def test_unset_means_everyone(self):
        assert self._settings().miniapp_allowed_user_ids is None
        assert self._settings(MINIAPP_ALLOWED_USER_IDS="  ").miniapp_allowed_user_ids is None

    def test_comma_separated_ids(self):
        assert self._settings(MINIAPP_ALLOWED_USER_IDS="12, 34,56").miniapp_allowed_user_ids == {12, 34, 56}

    @pytest.mark.parametrize("value", ["abc", "1,,2", "1,-2", "0", "1;2", "12 34"])
    def test_anything_else_stops_the_start(self, value):
        with pytest.raises(ValidationError):
            self._settings(MINIAPP_ALLOWED_USER_IDS=value)

    def test_static_dir_is_optional(self):
        assert self._settings().MINIAPP_STATIC_DIR is None
        assert self._settings(MINIAPP_STATIC_DIR="").MINIAPP_STATIC_DIR is None
        assert self._settings(MINIAPP_STATIC_DIR="/srv/app").MINIAPP_STATIC_DIR == "/srv/app"

    def test_the_api_needs_no_webhook_values_in_polling_mode(self):
        settings = self._settings(TELEGRAM_DELIVERY_MODE="polling", WEBHOOK_BASE="", WEBHOOK_SECRET="")

        assert settings.TELEGRAM_DELIVERY_MODE == "polling"
