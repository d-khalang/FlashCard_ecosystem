"""
Build every index the bot relies on. Idempotent; run it once on each new database, and
on existing ones after dedupe_expressions (the unique card index fails while duplicates exist).

Names follow MongoDB's defaults, so indexes already built by hand with the same keys
are left as they are. A duplicate user_id stops the run before anything is built: such
users must be merged by hand. Stays after the contract step, unlike the other migrations.

Dry run by default; --apply builds. Prints counts only. The dry run checks user_id only;
duplicate cards are what dedupe_expressions' dry run reports.
    python -m flashcard.migrations.ensure_indexes [--apply]
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass

from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService


@dataclass
class IndexReport:
    duplicate_user_ids: int = 0
    indexes_built: bool = False


async def ensure_indexes(cols: dict, users: UserService, expressions: ExpressionService, *, apply: bool) -> IndexReport:
    report = IndexReport()
    ids = Counter([doc.get("user_id") async for doc in cols["users"].find({}, {"user_id": 1})])
    report.duplicate_user_ids = sum(1 for count in ids.values() if count > 1)
    if apply and not report.duplicate_user_ids:
        await users.ensure_indexes()
        await expressions.ensure_indexes()
        report.indexes_built = True
    return report


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.language import LanguageConfig
    from flashcard.settings import get_setting
    settings = get_setting()

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await ensure_indexes(
            cols,
            UserService(users=cols["users"], defaults=LanguageConfig.from_settings(settings).user_defaults),
            ExpressionService(expressions=cols["expression"]),
            apply=apply,
        )
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}'")
    for field, value in vars(report).items():
        print(f"  {field}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the indexes the bot relies on.")
    parser.add_argument("--apply", action="store_true", help="build the indexes (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
