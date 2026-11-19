"""The migration that drops the conjugation cache the bot no longer reads."""
from flashcard.migrations.drop_conjugation_cache import drop_conjugation_cache


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    async def count_documents(self, query):
        assert query == {}
        return len(self.docs)


class FakeDb:
    def __init__(self, **collections):
        self.collections = {name: FakeCollection(docs) for name, docs in collections.items()}

    async def list_collection_names(self):
        return list(self.collections)

    def __getitem__(self, name):
        return self.collections[name]

    async def drop_collection(self, name):
        del self.collections[name]


async def test_dry_run_counts_and_keeps_the_collection():
    db = FakeDb(conjugations=[{"verb": "andare"}, {"verb": "fare"}])

    report = await drop_conjugation_cache(db, "conjugations", apply=False)

    assert (report.cached, report.dropped) == (2, False)
    assert "conjugations" in db.collections


async def test_apply_drops_it():
    db = FakeDb(conjugations=[{"verb": "andare"}], users=[{"user_id": "1"}])

    report = await drop_conjugation_cache(db, "conjugations", apply=True)

    assert (report.cached, report.dropped) == (1, True)
    assert set(db.collections) == {"users"}


async def test_a_missing_collection_is_nothing_to_do():
    db = FakeDb(users=[])

    report = await drop_conjugation_cache(db, "conjugations", apply=True)

    assert (report.cached, report.dropped) == (0, False)
