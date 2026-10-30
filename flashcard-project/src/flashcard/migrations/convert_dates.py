"""
Convert stored dates from ISO text to BSON dates.

Every writer now stores dates; older documents keep ISO text ("2026-10-01T10:00:00Z")
until this runs. Text without a timezone is taken as UTC, empty text becomes null
(missing). Text that is not a date is reported and left as it is: fix those documents
by hand, because the bot cannot read them (run the dry run before deploying to find
them). Each field is updated on its own and only if it still holds the text that was
read, so the run is safe while the bot is live: a field the bot rewrote meanwhile is
already a date, and the document's other fields are still converted. A second run
finds nothing to do.
Remove with the contract step, together with the legacy-text branches in the
scheduler and review-candidate queries.

Dry run by default; --apply writes. Prints counts and the ids of unreadable documents.
    python -m flashcard.migrations.convert_dates [--apply]
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field

from flashcard.utils.time import to_utc

# Every stored instant, by collection (nested paths in dot notation).
DATE_FIELDS = {
    "users": ["created_at", "last_push_at", "last_reviewed_at", "last_seen_at", "current_review.sent_at"],
    "expression": ["created_at", "last_sent_at", "last_interaction_at", "last_activity_at",
                   "last_review_at", "reverse_stats.last_review_at", "last_card.generated_at"],
}
MAX_LISTED_IDS = 50


@dataclass
class ConvertReport:
    documents_with_text: Counter = field(default_factory=Counter)  # per collection
    converted: Counter = field(default_factory=Counter)            # per "collection.field"
    emptied: Counter = field(default_factory=Counter)              # "" set to null
    unreadable: Counter = field(default_factory=Counter)           # left as text
    unreadable_ids: list = field(default_factory=list)             # "collection:_id field=value"
    changed_meanwhile: int = 0                                     # fields the bot rewrote (as dates) first


async def convert_dates(cols: dict, *, apply: bool) -> ConvertReport:
    report = ConvertReport()
    for collection, fields in DATE_FIELDS.items():
        query = {"$or": [{path: {"$type": "string"}} for path in fields]}
        async for doc in cols[collection].find(query):
            report.documents_with_text[collection] += 1
            for path in fields:
                value = _get(doc, path)
                if not isinstance(value, str):
                    continue
                key = f"{collection}.{path}"
                try:
                    converted = to_utc(value)
                except ValueError:
                    report.unreadable[key] += 1
                    if len(report.unreadable_ids) < MAX_LISTED_IDS:
                        report.unreadable_ids.append(f"{collection}:{doc['_id']} {path}={value!r}")
                    continue
                (report.converted if converted else report.emptied)[key] += 1
                if not apply:
                    continue
                result = await cols[collection].update_one({"_id": doc["_id"], path: value}, {"$set": {path: converted}})
                if not getattr(result, "modified_count", 0):
                    report.changed_meanwhile += 1
    return report


def _get(doc: dict, path: str):
    for part in path.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)
    return doc


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.settings import get_setting
    settings = get_setting()

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await convert_dates(cols, apply=apply)
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}'")
    for name, value in vars(report).items():
        if isinstance(value, Counter):
            value = dict(sorted(value.items()))
        if name == "unreadable_ids":
            print(f"  {name}:" + "".join(f"\n    {line}" for line in value))
            continue
        print(f"  {name}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert stored dates from ISO text to BSON dates.")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
