"""
One card per user and value (case-insensitive, accent-sensitive), enforced by the
unique index even when the pre-check misses a concurrent save.
"""
from unittest.mock import AsyncMock

from flashcard.services.expression import ExpressionService
from tests.helpers import AsyncCursorMock
from tests.integration.helpers import make_cols


async def _service(*values, user_id="42"):
    cols = make_cols(expressions=[{"user_id": user_id, "value": value} for value in values])
    service = ExpressionService(expressions=cols["expression"])
    await service.ensure_unique_value_index()
    return service, cols["expression"]


def _values(collection):
    return sorted(doc["value"] for doc in collection.docs)


async def test_concurrent_save_of_the_same_value_is_rejected_by_the_index():
    service, collection = await _service("ciao")
    collection.find_one = AsyncMock(return_value=None)  # the other save landed after the pre-check

    assert await service.add_expression(42, "Ciao") is False
    assert _values(collection) == ["ciao"]


async def test_accented_value_is_a_different_card():
    service, collection = await _service("perche")

    assert await service.add_expression(42, "perché") is True
    assert _values(collection) == ["perche", "perché"]


async def test_bulk_keeps_the_others_when_one_value_was_saved_concurrently():
    service, collection = await _service("ciao")
    collection.find = lambda *args, **kwargs: AsyncCursorMock([])  # pre-check misses the concurrent save

    inserted = await service.add_expressions_bulk(42, ["andare", "Ciao", "tavolo/a"])

    assert inserted == ["andare", "tavolo/a"]
    assert _values(collection) == ["andare", "ciao", "tavolo/a"]


async def test_bulk_drops_repeats_within_the_input_keeping_the_first_spelling_and_order():
    service, collection = await _service()

    inserted = await service.add_expressions_bulk(42, ["Ciao", "andare", "ciao", "ANDARE", "perché"])

    assert inserted == ["Ciao", "andare", "perché"]
    assert _values(collection) == ["Ciao", "andare", "perché"]
