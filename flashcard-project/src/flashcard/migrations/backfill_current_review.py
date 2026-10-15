"""
Backfill users.current_review from the legacy pending fields.

A user with `has_pending` gets the card whose `pending_message_id` is set (the latest
sent one if several are). Users who already have a current review are skipped, so the
run is idempotent and safe while the bot is live. Remove with the contract step.

Dry run by default; --apply writes. Prints counts only.
    python -m flashcard.migrations.backfill_current_review [--apply]
"""
import argparse
import asyncio
from dataclasses import dataclass

from flashcard.services.review_state import ReviewStateStore
from flashcard.utils.time import iso_z, now_utc


@dataclass
class BackfillReport:
    pending_users: int = 0
    already_set: int = 0
    backfilled: int = 0
    no_pending_card: int = 0
    invalid_message_id: int = 0
    non_string_user_id: int = 0


async def backfill_current_review(cols: dict, store: ReviewStateStore, *, apply: bool) -> BackfillReport:
    report = BackfillReport()
    async for user in cols["users"].find({"has_pending": True}):
        report.pending_users += 1
        if not isinstance(user["user_id"], str):
            # Every writer stores str ids; report anything else instead of guessing.
            report.non_string_user_id += 1
            continue
        if user.get("current_review") is not None:
            report.already_set += 1
            continue

        card = await _latest_pending_card(cols, user["user_id"])
        if card is None:
            # Nothing to point at; after the switch this user simply resumes.
            report.no_pending_card += 1
            continue
        try:
            message_id = int(card["pending_message_id"])
        except (TypeError, ValueError):
            report.invalid_message_id += 1
            continue

        sent_at = card.get("last_sent_at") or card.get("last_activity_at") or iso_z(now_utc())
        if not apply:
            report.backfilled += 1
        elif await store.backfill_from_legacy(user["user_id"], str(card["_id"]), message_id, sent_at):
            report.backfilled += 1
        else:
            report.already_set += 1
    return report


def _sent_order(card: dict) -> tuple:
    # last_sent_at is set together with pending_message_id; the rest only break ties.
    return (card.get("last_sent_at") or "", card.get("last_activity_at") or "", str(card["_id"]))


async def _latest_pending_card(cols: dict, user_id: str):
    # $ne: None, not $exists: grading leaves pending_message_id as null.
    cards = [card async for card in cols["expression"].find({"user_id": user_id, "pending_message_id": {"$ne": None}})]
    return max(cards, key=_sent_order, default=None)


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.settings import settings

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await backfill_current_review(cols, ReviewStateStore(users=cols["users"]), apply=apply)
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}'")
    for field, value in vars(report).items():
        print(f"  {field}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill users.current_review from legacy pending fields.")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
