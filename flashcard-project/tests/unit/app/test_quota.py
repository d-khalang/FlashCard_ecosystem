"""
Unit tests for QuotaPolicy: tier limits, the trial, own key and daily reset.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.quota import TRIAL_DAYS, Allowed, QuotaExceeded, QuotaPolicy
from flashcard.schemas.user import UserAPIConfig, UserTier
from flashcard.services.consumption import ConsumptionService
from flashcard.utils.time import iso_z, now_utc
from tests.helpers import TEST_LIMITS as LIMITS, make_user


def _today() -> str:
    return now_utc().date().isoformat()


def _service(settings=LIMITS):
    consumption = ConsumptionService(users=MagicMock())
    consumption.increment = AsyncMock()
    return QuotaPolicy(consumption, settings), consumption


def _days_ago(days: int) -> str:
    return iso_z(now_utc() - timedelta(days=days))


def _user(tier=UserTier.plus, *, cards=0, stories=0, date=None, **fields):
    user = make_user(user_id=1, tier=tier, **fields)
    user.consumption.consumption_date = date or _today()
    user.consumption.system_api.cards_generated = cards
    user.consumption.system_api.stories_generated = stories
    return user


class TestLimit:

    @pytest.mark.parametrize("tier, cards, stories", [
        (UserTier.admin, 999, 99),
        (UserTier.plus, 50, 10),
        (UserTier.digi, 40, 3),
    ])
    def test_tier_limits(self, tier, cards, stories):
        service, _ = _service()
        user = _user(tier)
        assert (service.limit(user, "cards"), service.limit(user, "stories")) == (cards, stories)

    @pytest.mark.parametrize("created_at", [None, _days_ago(5), _days_ago(TRIAL_DAYS - 1)])
    def test_normal_user_in_trial_gets_plus_limits(self, created_at):
        service, _ = _service()
        user = _user(UserTier.normal, created_at=created_at)
        assert (service.limit(user, "cards"), service.limit(user, "stories")) == (50, 10)

    @pytest.mark.parametrize("days", [TRIAL_DAYS, 20])
    def test_normal_user_after_trial_gets_normal_limits(self, days):
        service, _ = _service()
        user = _user(UserTier.normal, created_at=_days_ago(days))
        assert (service.limit(user, "cards"), service.limit(user, "stories")) == (10, 2)

    def test_trial_start_without_timezone_is_utc(self):
        service, _ = _service()
        naive = iso_z(now_utc() - timedelta(days=3)).removesuffix("Z")
        user = _user(UserTier.normal, created_at=naive)
        assert service.limit(user, "cards") == 50  # still in the trial: plus limits

    def test_limits_are_read_on_every_check(self):
        settings = SimpleNamespace(**vars(LIMITS))
        service, _ = _service(settings)
        settings.TIER_LIMITS_PLUS_CARDS = 7
        assert service.limit(_user(), "cards") == 7


class TestCheck:

    @pytest.mark.parametrize("kind, used, limit", [("cards", 49, 50), ("stories", 9, 10)])
    def test_below_limit_is_allowed(self, kind, used, limit):
        service, _ = _service()
        user = _user(**{kind: used})
        assert service.check(user, kind) == Allowed(uses_own_key=False)

    @pytest.mark.parametrize("kind, used, limit", [("cards", 50, 50), ("stories", 10, 10)])
    def test_at_limit_is_exceeded_with_tier_and_limit(self, kind, used, limit):
        service, _ = _service()
        user = _user(**{kind: used})
        assert service.check(user, kind) == QuotaExceeded(tier="plus", limit=limit)

    def test_trial_user_is_checked_against_plus_limit(self):
        service, _ = _service()
        user = _user(UserTier.normal, cards=10, created_at=_days_ago(1))
        assert service.check(user, "cards") == Allowed(uses_own_key=False)

    def test_usage_from_yesterday_does_not_count(self):
        service, _ = _service()
        yesterday = (now_utc() - timedelta(days=1)).date().isoformat()
        user = _user(cards=50, stories=10, date=yesterday)
        assert service.check(user, "cards") == Allowed(uses_own_key=False)
        assert service.check(user, "stories") == Allowed(uses_own_key=False)

    def test_admin_is_unlimited(self):
        service, _ = _service()
        user = _user(UserTier.admin, cards=9999, stories=9999)
        assert service.check(user, "cards") == Allowed(uses_own_key=False)

    def test_own_key_is_unlimited(self):
        service, _ = _service()
        user = _user(UserTier.normal, cards=9999, api_config=UserAPIConfig(api_key="test"))
        assert service.check(user, "cards") == Allowed(uses_own_key=True)


class TestRecord:

    @pytest.mark.parametrize("kind, metric", [("cards", "cards_generated"), ("stories", "stories_generated")])
    @pytest.mark.parametrize("own_key", [False, True])
    async def test_counts_under_the_checked_bucket(self, kind, metric, own_key):
        service, consumption = _service()
        await service.record(222, kind, Allowed(uses_own_key=own_key))
        consumption.increment.assert_awaited_once_with(222, metric, uses_own_key=own_key)
