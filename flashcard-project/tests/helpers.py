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
