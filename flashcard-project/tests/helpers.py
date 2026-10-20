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


from flashcard.language import LanguageConfig, UserDefaults

# The instance language used by tests: the shipped Italian defaults.
TEST_LANGUAGE = LanguageConfig(
    code="it",
    name="Italian",
    flag="🇮🇹",
    ui_locale="en",
    validator="auto",
    conjugation=True,
    user_defaults=UserDefaults(primary_language="en", secondary_language=None, target_level="A2"),
)


def make_user(**fields):
    """A UserDB with the test instance's default settings; `fields` override them."""
    from flashcard.schemas.user import UserDB

    return UserDB(**{**TEST_LANGUAGE.user_defaults.as_fields(), **fields})
