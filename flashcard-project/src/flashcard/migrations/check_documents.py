"""
Read every user and card the way the new image will, and report what it cannot read.

convert_dates only sees text dates. A bad language code, a null is_active or a numeric
date also makes a user unreadable, and there is no image rollback (rollout: fix forward),
so this is the last check before a deploy. Reads only; run it after every dry run in step 1.
Remove with the contract step.

Prints counts, field names and document ids, never the stored values. Exits with status 1
when anything is unreadable.
    python -m flashcard.migrations.check_documents
"""
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field

from pydantic import ValidationError

from flashcard.schemas.expression import Expression
from flashcard.services.user import UserService

MAX_LISTED_IDS = 50


@dataclass
class CheckReport:
    users: int = 0
    expressions: int = 0
    errors: Counter = field(default_factory=Counter)  # "collection.field: error type"
    unreadable: int = 0
    unreadable_ids: list = field(default_factory=list)  # "collection:_id"


async def check_documents(cols: dict, users: UserService) -> CheckReport:
    report = CheckReport()
    async for doc in cols["users"].find({}):
        report.users += 1
        _check("users", doc, users._to_user, report)
    async for doc in cols["expression"].find({}):
        report.expressions += 1
        _check("expression", doc, Expression.model_validate, report)
    return report


def _check(collection: str, doc: dict, read, report: CheckReport) -> None:
    try:
        read(doc)
    except ValidationError as error:
        report.unreadable += 1
        report.errors.update(
            f"{collection}.{'.'.join(str(part) for part in e['loc'])}: {e['type']}" for e in error.errors())
        if len(report.unreadable_ids) < MAX_LISTED_IDS:
            report.unreadable_ids.append(f"{collection}:{doc['_id']}")


async def _main() -> int:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.language import LanguageConfig
    from flashcard.settings import get_setting
    settings = get_setting()

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await check_documents(
            cols, UserService(users=cols["users"], defaults=LanguageConfig.from_settings(settings).user_defaults))
    finally:
        await close_mongo_on_client(client)
    print(f"READ ONLY on database '{settings.MONGO_DB}'")
    print(f"  users: {report.users}")
    print(f"  expressions: {report.expressions}")
    print(f"  unreadable: {report.unreadable}")
    print(f"  errors: {dict(sorted(report.errors.items()))}")
    print("  unreadable_ids:" + "".join(f"\n    {line}" for line in report.unreadable_ids))
    return 1 if report.unreadable else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
