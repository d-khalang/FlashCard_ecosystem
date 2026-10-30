from datetime import datetime, timezone
from typing import Annotated

from pydantic import BeforeValidator

UTC = timezone.utc

def now_utc() -> datetime:
    """Returns current UTC datetime"""
    return datetime.now(UTC)

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
