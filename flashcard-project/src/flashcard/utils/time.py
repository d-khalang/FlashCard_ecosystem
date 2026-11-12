from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from pydantic import BeforeValidator

UTC = timezone.utc

# How far the app's clock runs ahead of the real one. Always zero in production: only the dev
# runner (dev/miniapp_dev.py, never in the image) calls shift_clock, and a test checks that no
# code under src/ does.
_clock_offset = timedelta(0)


def now_utc() -> datetime:
    """The app's current UTC time: what reviews, cooldowns and daily limits count from."""
    return datetime.now(UTC) + _clock_offset


def real_now_utc() -> datetime:
    """The real UTC time, never shifted: for what others sign or stamp, such as Telegram's init data."""
    return datetime.now(UTC)


def shift_clock(offset: timedelta) -> None:
    """Dev only: run the app's clock `offset` ahead of the real one (timedelta(0) resets it)."""
    global _clock_offset
    if offset < timedelta(0):
        raise ValueError("the clock can only run ahead")
    _clock_offset = offset

def iso_z(ts: datetime) -> str:
    """
    Formats a datetime object to ISO 8601 string with 'Z' suffix and seconds precision.
    Format: YYYY-MM-DDTHH:MM:SSZ
    """
    # Ensure it's UTC and format like '2023-01-01T12:00:00Z'
    if ts.tzinfo is None:
        # Assuming UTC if no tzinfo, but safe to force it if intended
        ts = ts.replace(tzinfo=UTC)
        
    return ts.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

def parse_iso(iso_str: str) -> datetime:
    """
    Parses an ISO 8601 string with 'Z' suffix into a UTC-aware datetime object.
    """
    if iso_str.endswith('Z'):
        iso_str = iso_str.replace('Z', '+00:00')
    return datetime.fromisoformat(iso_str)


def to_utc(value) -> "datetime | None":
    """
    A stored instant as an aware UTC datetime. Accepts BSON dates and, until the
    `convert_dates` migration has run, the legacy ISO text. Naive values are UTC
    (every writer used UTC). None and "" (missing) read as None; anything else raises ValueError.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = parse_iso(value)
        except ValueError:
            raise ValueError(f"not an ISO date: {value!r}") from None
    if not isinstance(value, datetime):
        raise ValueError(f"not a date: {value!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# A stored instant: read with `to_utc`, written as a BSON date.
UtcDatetime = Annotated[datetime, BeforeValidator(to_utc)]
# The same, for a field that may be missing. Not Optional[UtcDatetime]: there the None
# that `to_utc` returns for "" still reaches the datetime check and is rejected.
OptionalUtcDatetime = Annotated[Optional[datetime], BeforeValidator(to_utc)]
