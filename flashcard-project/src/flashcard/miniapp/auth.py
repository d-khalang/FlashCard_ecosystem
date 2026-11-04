"""
Telegram Mini App sign-in: check `Telegram.WebApp.initData` against the bot token.

Pure: no I/O. The request dependency that applies it is in routes/deps.py.
Every request carries `Authorization: tma <initData>`; nothing is stored between requests.
"""
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl

# initData older than this is refused (Telegram only promises it is signed, not fresh).
MAX_AGE_SECONDS = 24 * 3600
# A clock a little ahead of Telegram's is normal; anything more is not a real signature date.
MAX_FUTURE_SECONDS = 30
MAX_INIT_DATA_CHARS = 16384


class InitDataError(ValueError):
    """The launch data could not be authenticated. The message never contains the data."""


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    username: Optional[str]
    # Telegram says the user allows the bot to write to them (the bot can start the chat).
    allows_write_to_pm: bool = False


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def validate_init_data(
    raw_init_data: str,
    *,
    bot_token: str,
    now: datetime,
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> TelegramIdentity:
    """
    Verify the bot-token HMAC (all decoded fields except `hash`, which includes the newer
    `signature` field when present) and the age of `auth_date`, and return the signed user's id
    and username. Raises InitDataError for anything else. `now` must be timezone-aware.
    """
    if not isinstance(raw_init_data, str) or not raw_init_data or len(raw_init_data) > MAX_INIT_DATA_CHARS:
        raise InitDataError("invalid initData")
    if not isinstance(bot_token, str) or not bot_token:
        raise ValueError("bot_token is required")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw_init_data):
        raise InitDataError("malformed initData encoding")
    try:
        pairs = parse_qsl(raw_init_data, keep_blank_values=True, strict_parsing=True,
                          encoding="utf-8", errors="strict", max_num_fields=64)
    except (ValueError, UnicodeError) as exc:
        raise InitDataError("malformed initData") from exc

    fields: dict[str, str] = {}
    for key, value in pairs:
        if not key or key in fields:
            raise InitDataError("duplicate or empty initData field")
        fields[key] = value

    received_hash = fields.get("hash", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", received_hash):
        raise InitDataError("missing or invalid hash")
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash.lower()):
        raise InitDataError("invalid initData signature")

    auth_date = fields.get("auth_date", "")
    if not re.fullmatch(r"[0-9]{1,12}", auth_date):
        raise InitDataError("invalid auth_date")
    current = now.astimezone(timezone.utc).timestamp()
    if int(auth_date) < current - max_age_seconds or int(auth_date) > current + MAX_FUTURE_SECONDS:
        raise InitDataError("initData outside permitted age")

    try:
        user = json.loads(fields["user"], parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        user_id, username = user.get("id"), user.get("username")
        if type(user_id) is not int or user_id < 1:
            raise ValueError("bad user id")
        if username is not None and not isinstance(username, str):
            raise ValueError("bad username")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise InitDataError("invalid user") from exc
    return TelegramIdentity(user_id=user_id, username=username, allows_write_to_pm=user.get("allows_write_to_pm") is True)
