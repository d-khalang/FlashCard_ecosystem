"""
Remove duplicate cards, then build the unique (user_id, value) index.

Cards saved before input was normalized, or by a double tap, can share a value that
differs only in case ("Ciao" / "ciao"). MongoDB groups the cards with the index's own
collation, so the migration merges exactly what the index would reject: accents stay
distinct ("perché" != "perche"), "ß" != "ss", and NFC/NFD spellings of one word merge.
No Python normalization matches that collation exactly (checked on MongoDB 7).

For each group the card with the most reviews (forward + reverse) stays; ties keep the
oldest. A removed card is treated like a /remove: a current_review that pointed at it is
cleared, and the legacy pause is cleared when the removed cards held the user's pending
message and no remaining card does.

Run after backfill_current_review. Idempotent: a second run finds no duplicates.
Deletes data: back up the database first. Remove with the contract step.

Dry run by default; --apply deletes and builds the index. Prints counts only.
    python -m flashcard.migrations.dedupe_expressions [--apply]
"""
import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from flashcard.schemas.user import parse_stored_user_id
from flashcard.services.expression import VALUE_COLLATION, ExpressionService
from flashcard.services.review_state import ReviewStateStore
from flashcard.utils.time import iso_z


@dataclass
class DedupeReport:
    expressions: int = 0
    duplicate_groups: int = 0
    removed: int = 0
    pending_cleared: int = 0
    current_review_cleared: int = 0
    invalid_user_id: int = 0  # not decimal text (the only stored form)
    non_string_value: int = 0
    index_built: bool = False


@dataclass
class _UserCards:
    kept: list = field(default_factory=list)
    removed: list = field(default_factory=list)


async def dedupe_expressions(
    cols: dict,
    expressions: ExpressionService,
    review_state: ReviewStateStore,
    *,
    apply: bool,
) -> DedupeReport:
    report = DedupeReport()
    users: dict[str, _UserCards] = defaultdict(_UserCards)
    async for group in await cols["expression"].aggregate(
        [{"$group": {"_id": {"user_id": "$user_id", "value": "$value"}, "cards": {"$push": "$$ROOT"}}}],
        collation=VALUE_COLLATION,
    ):
        cards = group["cards"]
        report.expressions += len(cards)
        if parse_stored_user_id(group["_id"].get("user_id")) is None:
            # Every writer stores decimal text; report anything else instead of guessing.
            report.invalid_user_id += len(cards)
            continue
        if not isinstance(group["_id"].get("value"), str):
            report.non_string_value += len(cards)
            continue
        keep = _card_to_keep(cards)
        user = users[cards[0]["user_id"]]
        user.kept.append(keep)
        if len(cards) > 1:
            report.duplicate_groups += 1
            user.removed.extend(card for card in cards if card is not keep)

    for user_id, cards in users.items():
        if not cards.removed:
            continue
        report.removed += len(cards.removed)
        removed_ids = {str(card["_id"]) for card in cards.removed}
        doc = await cols["users"].find_one({"user_id": user_id}, {"has_pending": 1, "current_review": 1}) or {}
        clears_current = ((doc.get("current_review") or {}).get("expression_id")) in removed_ids
        clears_pause = (doc.get("has_pending") is True
                        and any(_pending(card) for card in cards.removed)
                        and not any(_pending(card) for card in cards.kept))
        report.current_review_cleared += clears_current
        report.pending_cleared += clears_pause
        if not apply:
            continue

        await expressions.remove_duplicates([card["_id"] for card in cards.removed])
        if clears_pause:
            await review_state.clear_pending(parse_stored_user_id(user_id))
        if clears_current:
            await review_state.record_removed(parse_stored_user_id(user_id), doc["current_review"]["expression_id"])

    if apply:
        # Fails if duplicates remain (e.g. an invalid user_id or a non-string value reported above).
        await expressions.ensure_unique_value_index()
        report.index_built = True
    return report


def _pending(card: dict) -> bool:
    return card.get("pending_message_id") is not None


def _reviews(card: dict) -> int:
    return (card.get("reps") or 0) + ((card.get("reverse_stats") or {}).get("reps") or 0)


def _created_at(card: dict) -> str:
    # Legacy documents may store a BSON datetime instead of ISO text; missing sorts as oldest.
    value = card.get("created_at")
    return iso_z(value) if isinstance(value, datetime) else str(value or "")


def _card_to_keep(cards: list[dict]) -> dict:
    """Most reviews; ties keep the oldest (max returns the first of equal maxima)."""
    oldest_first = sorted(cards, key=lambda card: (_created_at(card), str(card["_id"])))
    return max(oldest_first, key=_reviews)


async def _main(apply: bool) -> None:
    from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
    from flashcard.settings import get_setting
    settings = get_setting()

    client, _, cols = await init_and_get_mongo(settings)
    try:
        report = await dedupe_expressions(
            cols,
            ExpressionService(expressions=cols["expression"]),
            ReviewStateStore(users=cols["users"]),
            apply=apply,
        )
    finally:
        await close_mongo_on_client(client)
    print(f"{'APPLIED' if apply else 'DRY RUN (nothing written)'} on database '{settings.MONGO_DB}'")
    for field, value in vars(report).items():
        print(f"  {field}: {value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove duplicate cards and build the unique value index.")
    parser.add_argument("--apply", action="store_true", help="delete duplicates and build the index (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))
