from datetime import datetime, timezone

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
