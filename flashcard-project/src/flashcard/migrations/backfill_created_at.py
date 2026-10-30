"""
Backfill users.created_at (the trial start) where it is missing.

Users created by a writer other than record_seen could miss created_at, which
gave them the trial limits forever. The trial start becomes their oldest saved
expression, the earliest evidence of use; users without expressions start their
trial at the run time. Never overwrites an existing created_at, so it is idempotent.

Dry run by default; --apply writes. Prints counts only.
    python -m flashcard.migrations.backfill_created_at [--apply]
"""
import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from flashcard.app.quota import TRIAL_DAYS
from flashcard.schemas.user import parse_stored_user_id
from flashcard.services.user import UserService
from flashcard.utils.time import UTC, iso_z, now_utc, parse_iso


@dataclass
class BackfillReport:
    missing: int = 0
    from_oldest_expression: int = 0
    from_run_time: int = 0
    trial_ends_now: int = 0  # oldest expression is older than the trial: limits drop to their tier
    invalid_user_id: int = 0  # not decimal text (the only stored form)
    already_set: int = 0
    unreadable_expression_dates: int = 0  # skipped when looking for the oldest expression


async def backfill_created_at(cols: dict, users: UserService, *, apply: bool) -> BackfillReport:
    report = BackfillReport()
    now = now_utc()
    async for user in cols["users"].find({"created_at": None}):
        report.missing += 1
        user_id = parse_stored_user_id(user["user_id"])
        if user_id is None:
            # Every writer stores decimal text; report anything else instead of guessing.
            report.invalid_user_id += 1
            continue

        oldest = await _oldest_expression_time(cols, user["user_id"], report)
        created_at = iso_z(oldest) if oldest else iso_z(now)
        if apply and not await users.backfill_created_at(user_id, created_at):
            report.already_set += 1
            continue

        if oldest is None:
            report.from_run_time += 1
        else:
            report.from_oldest_expression += 1
            if now - oldest >= timedelta(days=TRIAL_DAYS):
                report.trial_ends_now += 1
    return report


async def _oldest_expression_time(cols: dict, user_id: str, report: BackfillReport) -> Optional[datetime]:
    times = []
    async for doc in cols["expression"].find({"user_id": user_id}):
        parsed = _parse_time(doc.get("created_at"))
        if parsed is not None:
            times.append(parsed)
        elif doc.get("created_at"):
            report.unreadable_expression_dates += 1
    return min(times, default=None)


def _parse_time(value) -> Optional[datetime]:
    """UTC-aware datetime, or None for a missing or unreadable value. Naive values are taken as UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = parse_iso(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.language import LanguageConfig
    from flashcard.settings import get_setting
    settings = get_setting()

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await backfill_created_at(cols, UserService(users=cols["users"], defaults=LanguageConfig.from_settings(settings).user_defaults), apply=apply)
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}'")
    for field, value in vars(report).items():
        print(f"  {field}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill users.created_at where it is missing.")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
