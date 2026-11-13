"""
Unit tests for emptying the conjugation cache against the in-memory Mongo fake.
"""
from flashcard.migrations.clear_conjugation_cache import ClearReport, clear_conjugation_cache
from tests.integration.helpers import make_cols


def _cached(verb):
    return {"verb": verb, "data": {"queried": verb}}


async def test_dry_run_counts_and_keeps_everything():
    cols = make_cols(conjugations=[_cached("andare"), _cached("fare")])

    report = await clear_conjugation_cache(cols, apply=False)

    assert report == ClearReport(cached=2, deleted=0)
    assert len(cols["conjugation"].docs) == 2


async def test_apply_empties_only_the_conjugation_cache():
    cols = make_cols(users=[{"user_id": "42"}], expressions=[{"user_id": "42", "value": "andare"}],
                     conjugations=[_cached("andare"), _cached("fare")])

    report = await clear_conjugation_cache(cols, apply=True)

    assert report == ClearReport(cached=2, deleted=2)
    assert cols["conjugation"].docs == []
    assert len(cols["users"].docs) == 1 and len(cols["expression"].docs) == 1


async def test_an_empty_cache_is_fine():
    assert await clear_conjugation_cache(make_cols(), apply=True) == ClearReport()
