"""
Empty the conjugation cache (the bot's COLLECTION_CONJUGATION).

VerbService saves every it-conjugator answer and reads the saved copy first, so forms cached
before a conjugator data fix keep showing after the new image ships. Until it-conjugator-api's
build_db.py fix (2026-11-13), verbs first looked up after 2026-06-01 were cached with dialect or
archaic forms (andare: vò/và, fare: fazzo/face). The cache is rebuilt on demand from the API,
so emptying it loses nothing.

Run it only after the fixed conjugator image is live: a lookup in between would cache the old
forms again. Dry run by default; --apply deletes. Prints counts only.
    python -m flashcard.migrations.clear_conjugation_cache [--apply]
"""
import argparse
import asyncio
from dataclasses import dataclass


@dataclass
class ClearReport:
    cached: int = 0
    deleted: int = 0


async def clear_conjugation_cache(cols: dict, *, apply: bool) -> ClearReport:
    report = ClearReport()
    async for _ in cols["conjugation"].find({}):
        report.cached += 1
    if apply:
        report.deleted = (await cols["conjugation"].delete_many({})).deleted_count
    return report


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.settings import get_setting
    settings = get_setting()

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await clear_conjugation_cache(cols, apply=apply)
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}', "
          f"collection '{settings.COLLECTION_CONJUGATION}'")
    for field, value in vars(report).items():
        print(f"  {field}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Empty the conjugation cache after a conjugator data fix.")
    parser.add_argument("--apply", action="store_true", help="delete the cached conjugations (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
