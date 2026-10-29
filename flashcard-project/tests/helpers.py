"""
Shared test helpers for the FlashCard test suite.

Reusable mocks and utilities used across multiple test files.
"""


class AsyncCursorMock:
    """Wraps a list as an async iterator to simulate a MongoDB cursor.

    Usage:
        cols["expression"].find = MagicMock(return_value=AsyncCursorMock([doc1, doc2]))
    """

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


from types import SimpleNamespace

from flashcard.language import LanguageConfig, UserDefaults
from flashcard.services.i18n import I18nService

# The instance language used by tests: the shipped Italian defaults.
TEST_LANGUAGE = LanguageConfig(
    code="it",
    name="Italian",
    flag="🇮🇹",
    ui_locale="en",
    validator="italian",
    conjugation=True,
    user_defaults=UserDefaults(primary_language="en", secondary_language=None, target_level="A2"),
)

# What the composition root injects as `i18n` for TEST_LANGUAGE.
TEST_I18N = I18nService.for_language(TEST_LANGUAGE)


def make_user(**fields):
    """A UserDB with the test instance's default settings; `fields` override them."""
    from flashcard.schemas.user import UserDB

    return UserDB(**{**TEST_LANGUAGE.user_defaults.as_fields(), **fields})


# Fixed tier limits for tests, independent of .env.
TEST_LIMITS = SimpleNamespace(
    TIER_LIMITS_NORMAL_CARDS=10, TIER_LIMITS_NORMAL_STORIES=2,
    TIER_LIMITS_DIGI_CARDS=40, TIER_LIMITS_DIGI_STORIES=3,
    TIER_LIMITS_PLUS_CARDS=50, TIER_LIMITS_PLUS_STORIES=10,
    TIER_LIMITS_ADMIN_CARDS=999, TIER_LIMITS_ADMIN_STORIES=99,
)


def make_quota(consumption, exceeded=None):
    """
    A real QuotaPolicy that counts through `consumption` (a mock with an
    `increment` AsyncMock). `check` is a spy; `exceeded` (a QuotaExceeded)
    makes every check return it.
    """
    from unittest.mock import MagicMock

    from flashcard.app.quota import QuotaPolicy
    from flashcard.services.consumption import ConsumptionService

    consumption.resolve_consumption = ConsumptionService(users=None).resolve_consumption
    quota = QuotaPolicy(consumption, TEST_LIMITS)
    quota.check = MagicMock(wraps=quota.check) if exceeded is None else MagicMock(return_value=exceeded)
    return quota
