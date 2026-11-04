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
