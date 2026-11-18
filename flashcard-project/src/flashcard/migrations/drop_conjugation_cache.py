"""
Drop the old conjugation cache (the collection named by COLLECTION_CONJUGATION).

Since the Verbs page (docs/verbs/contract.md section 5) the bot reads the conjugator directly and
never reads or writes this collection, so dropping it loses nothing. Run it after the release that
stops using the cache is live on the database's bot and Mini App (an older bot would refill it).

Dry run by default; --apply drops. Prints counts only.
    python -m flashcard.migrations.drop_conjugation_cache [--apply]
"""
import argparse
import asyncio
from dataclasses import dataclass


@dataclass
class DropReport:
    cached: int = 0
    dropped: bool = False


async def drop_conjugation_cache(db, name: str, *, apply: bool) -> DropReport:
    report = DropReport()
    if name not in await db.list_collection_names():
        return report
    report.cached = await db[name].count_documents({})
    if apply:
        await db.drop_collection(name)
        report.dropped = True
    return report


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.settings import get_setting
    settings = get_setting()

    client, db, _ = await init_and_get_mongo(settings)
    try:
        report = await drop_conjugation_cache(db, settings.COLLECTION_CONJUGATION, apply=apply)
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}', "
          f"collection '{settings.COLLECTION_CONJUGATION}'")
    for field, value in vars(report).items():
        print(f"  {field}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drop the conjugation cache the bot no longer uses.")
    parser.add_argument("--apply", action="store_true", help="drop the collection (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
