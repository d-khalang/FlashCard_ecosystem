"""Local dev runner for the Mini App backend. Dev bot and loopback Mongo only; never production.

    python dev/miniapp_dev.py serve    # sign init data, write miniapp/.env.local, run the API
    python dev/miniapp_dev.py seed     # add 5 sample words for the dev user
    python dev/miniapp_dev.py init-data  # only refresh VITE_DEV_INIT_DATA (valid 24 h)
    python dev/miniapp_dev.py check    # validate .env.dev, change nothing

Run from flashcard-project/. The API listens on 127.0.0.1:8765. Values come from `.env.dev`
(see `.env.dev.example`); it never reads `.env`. The dev bot's token signs real Telegram-format
init data for the dev user, so the API's sign-in is the production code path.

Nothing secret is printed: not tokens, not init data, not keys. Errors name variables, not values.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

HOST, PORT = "127.0.0.1", 8765
FRONTEND_ENV = ROOT / "miniapp" / ".env.local"
FRONTEND_VAR = "VITE_DEV_INIT_DATA"

SEED_WORDS = {
    "it": ["ciao", "bene", "mare", "andare", "piacere"],
    "en": ["hello", "breeze", "though", "tidy", "wander"],
}
LANGUAGE_NAMES = {"it": ("Italian", "🇮🇹", "italian"), "en": ("English", "🇬🇧", "latin")}
DEFAULT_MONGO = "mongodb://127.0.0.1:27019/?directConnection=true"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class SetupError(SystemExit):
    """A problem with the dev setup; the message never contains values."""


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a dotenv file. Values are never printed."""
    if not path.is_file():
        raise SetupError(f"Missing {path.name}: copy .env.dev.example to {path.name} and fill it in")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def pick(values: dict[str, str], *names: str) -> tuple[str | None, str | None]:
    """The first non-empty value among `names`, and the name it came from."""
    for name in names:
        if values.get(name):
            return values[name], name
    return None, None


def load_env(path: Path) -> dict:
    values = read_env_file(path)
    language, _ = pick(values, "KARTINO_DEV_LANGUAGE", "LEARNING_LANGUAGE_CODE")
    if language is None:
        language = "it" if values.get("KARTINO_STAGE_IT_BOT_TOKEN") and not values.get("KARTINO_STAGE_EN_BOT_TOKEN") else "en"
    if language not in LANGUAGE_NAMES:
        raise SetupError("The language (KARTINO_DEV_LANGUAGE) must be it or en")

    token_raw, _ = pick(values, "KARTINO_DEV_BOT_TOKEN", f"KARTINO_STAGE_{language.upper()}_BOT_TOKEN", "BOT_TOKEN")
    user_raw, _ = pick(values, "KARTINO_DEV_USER_ID", "ADMIN_ID")
    groq_key, _ = pick(values, "KARTINO_DEV_GROQ_KEY", "GROQ_ASSIST_KEY")
    missing = [name for name, value in (
        (f"KARTINO_DEV_BOT_TOKEN (or KARTINO_STAGE_{language.upper()}_BOT_TOKEN)", token_raw),
        ("KARTINO_DEV_USER_ID (or ADMIN_ID)", user_raw),
        ("KARTINO_DEV_GROQ_KEY (or GROQ_ASSIST_KEY)", groq_key),
    ) if not value]
    if missing:
        raise SetupError("Missing in .env.dev: " + ", ".join(missing))

    # The value may carry trailing text; only the first word is the token.
    token = token_raw.split()[0]
    bot_id, _, secret = token.partition(":")
    if not bot_id.isdigit() or not secret:
        raise SetupError("The bot token is not a bot token (expected <digits>:<secret>)")
    try:
        user_id = int(user_raw.split()[0])
    except ValueError:
        raise SetupError("The dev user id is not a number") from None
    if user_id < 1:
        raise SetupError("The dev user id must be positive")

    uri, uri_name = pick(values, "KARTINO_DEV_MONGO_URI", "MONGO_URI")
    uri = uri or DEFAULT_MONGO
    if not all_hosts_are_loopback(uri):
        raise SetupError(f"{uri_name or 'The Mongo URI'} must point to loopback; the dev runner never uses another server")
    database, _ = pick(values, "KARTINO_DEV_MONGO_DB", "MONGO_DB")
    model, _ = pick(values, "KARTINO_DEV_GROQ_MODEL", "LLM_GROQ_MODEL")
    return {"language": language, "token": token, "user_id": user_id, "groq_key": groq_key, "uri": uri,
            "database": database or f"kartino_dev_{language}", "groq_model": model}


def uri_hosts(uri: str) -> list[str]:
    """Every host of a MongoDB URI (a seed list has several), without credentials and ports."""
    parts = urlsplit(uri)
    if parts.scheme != "mongodb":  # mongodb+srv resolves hosts from DNS: not checkable here
        return ["?"]
    netloc = parts.netloc.rpartition("@")[2]
    hosts = []
    for entry in netloc.split(","):
        if entry.startswith("["):  # [::1]:27017
            hosts.append(entry[1:].partition("]")[0])
        else:
            hosts.append(entry.partition(":")[0])
    return [host.lower() for host in hosts if host] or ["?"]


def all_hosts_are_loopback(uri: str) -> bool:
    return all(host in LOOPBACK for host in uri_hosts(uri))


def sign_init_data(env: dict) -> str:
    """Telegram-format initData for the dev user, signed with the dev bot's token."""
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": env["user_id"], "first_name": "Dev", "username": "dev"}, separators=(",", ":")),
        "query_id": "dev",
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", env["token"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def write_frontend_env(init_data: str) -> None:
    """Set VITE_DEV_INIT_DATA in miniapp/.env.local (git-ignored), keeping its other lines."""
    lines = FRONTEND_ENV.read_text(encoding="utf-8").splitlines() if FRONTEND_ENV.is_file() else []
    lines = [line for line in lines if not line.startswith(f"{FRONTEND_VAR}=")]
    lines.append(f"{FRONTEND_VAR}={init_data}")
    FRONTEND_ENV.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_settings(env: dict, key_file: Path):
    """Settings from dev values only; no .env is read."""
    from pydantic import ValidationError
    from flashcard.settings import Settings

    name, flag, validator = LANGUAGE_NAMES[env["language"]]
    os.environ.update({
        "BOT_TOKEN": env["token"], "LOGGER_BOT_TOKEN": env["token"], "ADMIN_ID": str(env["user_id"]),
        "MONGO_URI": env["uri"], "MONGO_DB": env["database"],
        "COLLECTION_USERS": "users", "COLLECTION_EXPRESSION": "expression", "COLLECTION_CONJUGATION": "conjugation",
        "ENABLE_CONJUGATION": "false", "TELEGRAM_DELIVERY_MODE": "polling",
        "LEARNING_LANGUAGE_CODE": env["language"], "LEARNING_LANGUAGE_NAME": name, "LEARNING_LANGUAGE_FLAG": flag,
        "LANGUAGE_VALIDATOR": validator, "LLM_KEY_FILE": str(key_file),
        "MINIAPP_ALLOWED_USER_IDS": str(env["user_id"]),
    })
    if env["groq_model"]:
        os.environ["LLM_GROQ_MODEL"] = env["groq_model"]
    os.environ.pop("MINIAPP_STATIC_DIR", None)  # the frontend runs on Vite in development
    try:
        return Settings(_env_file=None)
    except ValidationError as error:  # its text would repeat the values
        fields = ", ".join(sorted({str(e["loc"][0]) for e in error.errors()}))
        raise SetupError(f"Invalid settings: {fields}") from None


def with_settings(env: dict, run):
    """Call run(settings) with an LLM key file that exists only while it runs."""
    with tempfile.TemporaryDirectory(prefix="kartino-dev-") as directory:
        key_file = Path(directory) / "llm_key.json"
        key_file.write_text(json.dumps({"core": [{"name": "dev", "api_key": env["groq_key"], "provider": "groq"}],
                                        "reminder": [], "users": {}}), encoding="utf-8")
        return run(make_settings(env, key_file))


def serve(env: dict) -> None:
    import uvicorn
    from flashcard.miniapp.api import create_app

    def run(settings):
        app = create_app(settings)
        print(f"Mini App API on http://{HOST}:{PORT}/api/v1 as the dev user (database {env['database']})")
        uvicorn.run(app, host=HOST, port=PORT, log_level="info")

    refresh_init_data(env)
    with_settings(env, run)


def refresh_init_data(env: dict) -> None:
    write_frontend_env(sign_init_data(env))
    print(f"Wrote {FRONTEND_VAR} to miniapp/.env.local (valid 24 hours; rerun to refresh)")


async def seed(settings, env: dict) -> None:
    """Indexes, the dev user (through record_seen, the one creator) and the sample words."""
    from pymongo.errors import DuplicateKeyError
    from flashcard.composition import build_core, open_resources
    from flashcard.language import LanguageConfig
    from flashcard.schemas.expression import ExpressionDB

    async with open_resources(settings) as resources:
        core = build_core(resources.cols, resources.http_client, settings, LanguageConfig.from_settings(settings))
        await core.expression_service.ensure_indexes()
        await core.user_service.ensure_indexes()
        await core.user_service.record_seen(env["user_id"], "dev")
        # Created 3 days ago: a word nobody has reviewed is ready once its cooldown (12 h) has passed.
        created = datetime.now(timezone.utc) - timedelta(days=3)
        added = 0
        for word in SEED_WORDS[env["language"]]:
            document = ExpressionDB(user_id=str(env["user_id"]), value=word, created_at=created).model_dump()
            try:
                await resources.cols["expression"].insert_one(document)
                added += 1
            except DuplicateKeyError:
                pass
        print(f"Dev user ready; added {added} of {len(SEED_WORDS[env['language']])} sample words "
              f"(database {env['database']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "seed", "init-data", "check"))
    parser.add_argument("--env-file", default=str(PROJECT / ".env.dev"), help="default: flashcard-project/.env.dev")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    env = load_env(Path(args.env_file))
    if args.command == "check":
        print(f"OK: language {env['language']}, database {env['database']} on loopback, dev user and keys present")
    elif args.command == "init-data":
        refresh_init_data(env)
    elif args.command == "seed":
        with_settings(env, lambda settings: asyncio.run(seed(settings, env)))
    else:
        try:
            serve(env)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
