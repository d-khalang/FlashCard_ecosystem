from flashcard.miniapp.rate_limit import RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_allows_up_to_the_limit_then_says_how_long_to_wait():
    clock = Clock()
    limiter = RateLimiter(3, 60, clock)

    assert [limiter.hit("a") for _ in range(3)] == [0, 0, 0]
    clock.now += 10
    assert limiter.hit("a") == 50


def test_the_window_slides():
    clock = Clock()
    limiter = RateLimiter(2, 60, clock)
    limiter.hit("a")
    clock.now += 30
    limiter.hit("a")
    assert limiter.hit("a") == 30

    clock.now += 30  # the first hit has left the window
    assert limiter.hit("a") == 0


def test_refused_requests_are_not_counted():
    clock = Clock()
    limiter = RateLimiter(1, 60, clock)
    limiter.hit("a")
    for _ in range(5):
        assert limiter.hit("a") > 0

    clock.now += 60
    assert limiter.hit("a") == 0


def test_each_key_has_its_own_budget():
    limiter = RateLimiter(1, 60, Clock())

    assert limiter.hit(1) == 0 and limiter.hit(2) == 0
    assert limiter.hit(1) > 0


def test_retry_after_is_at_least_one_second():
    clock = Clock()
    limiter = RateLimiter(1, 60, clock)
    limiter.hit("a")
    clock.now += 59.9

    assert limiter.hit("a") == 1


class TestDailyBudget:

    def _budget(self, limit, start):
        from flashcard.miniapp.rate_limit import DailyBudget
        now = [start]
        return DailyBudget(limit, clock=lambda: now[0]), now

    def test_allows_up_to_the_limit_per_user_then_says_when_the_day_ends(self):
        from datetime import datetime, timezone
        budget, _ = self._budget(2, datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc))

        assert [budget.charge(1), budget.charge(1)] == [0, 0]
        assert budget.charge(1) == 2 * 3600
        assert budget.charge(2) == 0

    def test_a_new_day_starts_again_and_drops_the_old_one(self):
        from datetime import datetime, timedelta, timezone
        budget, now = self._budget(1, datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc))
        for user in range(100):
            budget.charge(user)
        assert len(budget._used) == 100

        now[0] += timedelta(minutes=2)

        assert budget.charge(0) == 0
        assert len(budget._used) == 1  # yesterday's 100 entries are gone

    def test_the_wait_is_at_least_one_second(self):
        from datetime import datetime, timezone
        budget, _ = self._budget(1, datetime(2026, 1, 1, 23, 59, 59, 900000, tzinfo=timezone.utc))
        budget.charge(1)

        assert budget.charge(1) == 1

    def test_the_configured_default_is_well_above_twice_the_biggest_card_limit(self):
        from flashcard.settings import get_setting
        settings = get_setting()
        biggest = max(settings.TIER_LIMITS_NORMAL_CARDS, settings.TIER_LIMITS_DIGI_CARDS, settings.TIER_LIMITS_PLUS_CARDS)

        assert settings.MINIAPP_LLM_DAILY_ATTEMPTS == 300 >= 3 * 2 * biggest
