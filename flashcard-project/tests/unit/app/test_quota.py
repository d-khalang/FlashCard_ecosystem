"""
Unit tests for QuotaPolicy: tier limits, card credits, the trial, own key and daily reset.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.quota import (
    CARD_CREDITS, SECTION_CREDITS, TRIAL_DAYS, Allowed, QuotaExceeded, QuotaPolicy,
)
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


def _user(tier=UserTier.plus, *, credits=0, stories=0, date=None, **fields):
    user = make_user(user_id=1, tier=tier, **fields)
    user.consumption.consumption_date = date or _today()
    user.consumption.system_api.credits_used = credits
    user.consumption.system_api.stories_generated = stories
    return user


class TestLimit:

    @pytest.mark.parametrize("tier, credits, stories", [
        (UserTier.admin, 1998, 99),
        (UserTier.plus, 100, 10),
        (UserTier.digi, 80, 3),
    ])
    def test_tier_limits(self, tier, credits, stories):
        service, _ = _service()
        user = _user(tier)
        assert (service.limit(user, "cards"), service.limit(user, "stories")) == (credits, stories)

    @pytest.mark.parametrize("created_at", [None, _days_ago(5), _days_ago(TRIAL_DAYS - 1)])
    def test_normal_user_in_trial_gets_plus_limits(self, created_at):
        service, _ = _service()
        user = _user(UserTier.normal, created_at=created_at)
        assert (service.limit(user, "cards"), service.limit(user, "stories")) == (100, 10)

    @pytest.mark.parametrize("days", [TRIAL_DAYS, 20])
    def test_normal_user_after_trial_gets_normal_limits(self, days):
        service, _ = _service()
        user = _user(UserTier.normal, created_at=_days_ago(days))
        assert (service.limit(user, "cards"), service.limit(user, "stories")) == (20, 2)

    def test_trial_start_without_timezone_is_utc(self):
        service, _ = _service()
        naive = iso_z(now_utc() - timedelta(days=3)).removesuffix("Z")
        user = _user(UserTier.normal, created_at=naive)
        assert service.limit(user, "cards") == 100  # still in the trial: plus limits

    def test_limits_are_read_on_every_check(self):
        settings = SimpleNamespace(**vars(LIMITS))
        service, _ = _service(settings)
        settings.TIER_LIMITS_PLUS_CREDITS = 7
        assert service.limit(_user(), "cards") == 7


class TestCheck:

    def test_a_new_card_costs_two_credits_and_a_part_one(self):
        assert (CARD_CREDITS, SECTION_CREDITS) == (2, 1)

    def test_a_new_card_fits_with_two_credits_left(self):
        service, _ = _service()
        assert service.check(_user(credits=98), "cards") == Allowed(uses_own_key=False, credits=2)

    def test_with_one_credit_left_a_part_fits_but_a_new_card_does_not(self):
        service, _ = _service()
        user = _user(credits=99)
        assert service.check(user, "cards") == QuotaExceeded(tier="plus", limit=100)
        assert service.check(user, "cards", credits=SECTION_CREDITS) == Allowed(uses_own_key=False, credits=1)

    def test_no_credit_left_refuses_a_part(self):
        service, _ = _service()
        assert service.check(_user(credits=100), "cards", credits=SECTION_CREDITS) == QuotaExceeded(
            tier="plus", limit=100)

    def test_old_card_counts_do_not_spend_credits(self):
        service, _ = _service()
        user = _user()
        user.consumption.system_api.cards_generated = 500
        assert service.check(user, "cards") == Allowed(uses_own_key=False, credits=2)

    def test_stories_count_one_each_and_carry_no_credits(self):
        service, _ = _service()
        assert service.check(_user(stories=9), "stories") == Allowed(uses_own_key=False)
        assert service.check(_user(stories=10), "stories") == QuotaExceeded(tier="plus", limit=10)

    def test_trial_user_is_checked_against_plus_limit(self):
        service, _ = _service()
        user = _user(UserTier.normal, credits=20, created_at=_days_ago(1))
        assert service.check(user, "cards") == Allowed(uses_own_key=False, credits=2)

    def test_usage_from_yesterday_does_not_count(self):
        service, _ = _service()
        yesterday = (now_utc() - timedelta(days=1)).date().isoformat()
        user = _user(credits=100, stories=10, date=yesterday)
        assert service.check(user, "cards") == Allowed(uses_own_key=False, credits=2)
        assert service.check(user, "stories") == Allowed(uses_own_key=False)

    def test_admin_is_unlimited(self):
        service, _ = _service()
        user = _user(UserTier.admin, credits=99999, stories=9999)
        assert service.check(user, "cards") == Allowed(uses_own_key=False, credits=2)

    def test_own_key_is_unlimited_and_still_priced(self):
        service, _ = _service()
        user = _user(UserTier.normal, credits=9999, api_config=UserAPIConfig(api_key="test"))
        assert service.check(user, "cards", credits=1) == Allowed(uses_own_key=True, credits=1)


class TestUsage:

    def test_cards_usage_is_in_credits(self):
        service, _ = _service()
        usage = service.usage(_user(credits=34), "cards")
        assert (usage.used, usage.limit) == (34, 100)


class TestRecord:

    @pytest.mark.parametrize("own_key", [False, True])
    @pytest.mark.parametrize("credits", [CARD_CREDITS, SECTION_CREDITS])
    async def test_a_card_counts_once_and_spends_its_credits_in_the_checked_bucket(self, own_key, credits):
        service, consumption = _service()
        await service.record(222, "cards", Allowed(uses_own_key=own_key, credits=credits))
        consumption.increment.assert_awaited_once_with(
            222, "cards_generated", uses_own_key=own_key, credits=credits)

    @pytest.mark.parametrize("own_key", [False, True])
    async def test_a_story_counts_once_without_credits(self, own_key):
        service, consumption = _service()
        await service.record(222, "stories", Allowed(uses_own_key=own_key))
        consumption.increment.assert_awaited_once_with(222, "stories_generated", uses_own_key=own_key)

