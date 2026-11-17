"""Local dev runner for the Mini App backend. Dev bot and loopback Mongo only; never production.

    python dev/miniapp_dev.py serve    # sign init data, write miniapp/.env.local, run the API
    python dev/miniapp_dev.py seed     # reset the dev user to a profile (default: ready; see --profile)
    python dev/miniapp_dev.py init-data  # only refresh VITE_DEV_INIT_DATA (valid 24 h)
    python dev/miniapp_dev.py check    # validate .env.dev, change nothing
    python dev/miniapp_dev.py tunnel   # try the Mini App from a phone through a temporary https tunnel

Tunnel mode needs KARTINO_PROD_BOT_IDS (to refuse production bots) and cloudflared. It serves a production
build through the API only, refuses init data older than 1 hour, and checks for leaks before and while
it runs.

Run from flashcard-project/. The API listens on 127.0.0.1:8765. Values come from `.env.dev`
(see `.env.dev.example`); it never reads `.env`. The dev bot's token signs real Telegram-format
init data for the dev user, so the API's sign-in is the production code path.

Seed profiles (`seed --profile NAME`) replace the dev user's words and daily usage in the dev database:
    ready     5 words, never reviewed, all due
    empty     the dev user with no words
    reviewed  words with history: 2 due (one often missed), 2 resting (reviewed an hour ago), 1 new
    limit     like ready, with today's card credits used up

`--days-ahead N` runs the app's clock N days ahead (serve, tunnel, seed), e.g. to see resting words come
due. Sign-in still uses the real time. It lives only in this process; production never shifts its clock.

Nothing secret is printed: not tokens, not init data, not keys. Errors name variables, not values.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
sys.path.insert(0, str(PROJECT / "src"))

HOST, PORT = "127.0.0.1", 8765
ORIGINAL_ENVIRON = dict(os.environ)  # before make_settings adds tokens; what child processes get
FRONTEND_ENV = ROOT / "miniapp" / ".env.local"
FRONTEND_VAR = "VITE_DEV_INIT_DATA"
API_ME = "/api/v1/me"

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


def load_env(path: Path, tunnel: bool = False) -> dict:
    """
    Dev values from .env.dev. The bot is the shadow bot of KARTINO_DEV_LANGUAGE
    (KARTINO_EN_SHADOW_BOT_TOKEN or KARTINO_IT_SHADOW_BOT_TOKEN). A token whose bot id is in
    KARTINO_PROD_BOT_IDS is refused; the tunnel requires that list.
    """
    values = read_env_file(path)
    language = values.get("KARTINO_DEV_LANGUAGE") or "en"
    if language not in LANGUAGE_NAMES:
        raise SetupError("The language (KARTINO_DEV_LANGUAGE) must be it or en")

    token_name = f"KARTINO_{language.upper()}_SHADOW_BOT_TOKEN"
    token_raw = values.get(token_name)
    user_raw = values.get("KARTINO_DEV_USER_ID")
    groq_key = values.get("KARTINO_DEV_GROQ_KEY")
    prod_ids_raw = values.get("KARTINO_PROD_BOT_IDS")
    required = [(token_name, token_raw), ("KARTINO_DEV_USER_ID", user_raw), ("KARTINO_DEV_GROQ_KEY", groq_key)]
    if tunnel:
        required.append(("KARTINO_PROD_BOT_IDS (production bot ids, so the tunnel can refuse them)", prod_ids_raw))
    missing = [name for name, value in required if not value]
    if missing:
        raise SetupError("Missing in .env.dev: " + ", ".join(missing))

    # The value may carry trailing text; only the first word is the token.
    token = token_raw.split()[0]
    bot_id, _, secret = token.partition(":")
    if not bot_id.isdigit() or not secret:
        raise SetupError("The bot token is not a bot token (expected <digits>:<secret>)")
    prod_ids = {part.strip() for part in (prod_ids_raw or "").split(",") if part.strip()}
    if not all(part.isdigit() for part in prod_ids):
        raise SetupError("KARTINO_PROD_BOT_IDS must be comma-separated bot ids (the digits before ':')")
    if bot_id in prod_ids:
        raise SetupError(f"{token_name} belongs to a production bot (its id is in KARTINO_PROD_BOT_IDS)")
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
    # Split by hand: urlsplit refuses a seed list that holds an IPv6 host on newer Python versions.
    scheme, _, rest = uri.partition("://")
    if scheme != "mongodb":  # mongodb+srv resolves hosts from DNS: not checkable here
        return ["?"]
    netloc = rest.split("/", 1)[0].split("?", 1)[0].rpartition("@")[2]
    hosts = []
    for entry in netloc.split(","):
        if entry.startswith("["):  # [::1]:27017
            hosts.append(entry[1:].partition("]")[0])
        else:
            hosts.append(entry.partition(":")[0])
    return [host.lower() for host in hosts if host] or ["?"]


def all_hosts_are_loopback(uri: str) -> bool:
    return all(host in LOOPBACK for host in uri_hosts(uri))


def sign_init_data(env: dict, auth_date: int | None = None) -> str:
    """Telegram-format initData for the dev user, signed with the dev bot's token."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
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
    os.environ.pop("MINIAPP_INIT_DATA_MAX_AGE_SECONDS", None)
    os.environ.update(env.get("settings_extra", {}))  # tunnel mode: built frontend, short init-data age
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


SEED_PROFILES = ("ready", "empty", "reviewed", "limit")
# The commands that run the app, so the only ones a shifted clock means anything to.
CLOCK_COMMANDS = ("serve", "tunnel", "seed")
MAX_DAYS_AHEAD = 3650
# More than any tier's daily credit limit.
USED_UP_CREDITS = 10_000


def profile_documents(profile: str, user_id: int, words: list[str], now: datetime) -> tuple[dict, list[dict]]:
    """The dev user's fields and word documents for `profile`, with every time counted from `now`."""
    from flashcard.schemas.expression import ExpressionDB

    if profile not in SEED_PROFILES:
        raise SetupError(f"Unknown profile {profile!r}; choose from {', '.join(SEED_PROFILES)}")
    user_fields: dict = {}
    if profile == "limit":
        user_fields = {"consumption.consumption_date": now.date().isoformat(),
                       "consumption.system_api.credits_used": USED_UP_CREDITS}
    if profile == "empty":
        return user_fields, []
    # Created 3 days ago: a word nobody has reviewed is ready once its cooldown (12 h) has passed.
    created = now - timedelta(days=3)
    documents = [ExpressionDB(user_id=str(user_id), value=word, created_at=created).model_dump() for word in words]
    if profile == "reviewed":
        history = [  # (hours since the last review, reps, lapses, streak, last grade)
            (48, 3, 0, 3, 5), (48, 4, 3, 0, 1),  # due: one known, one often missed
            (1, 2, 0, 2, 4), (1, 1, 1, 0, 2),    # resting: reviewed an hour ago
        ]  # one entry fewer than words on purpose: zip leaves the last word as the new one
        for document, (hours, reps, lapses, streak, grade) in zip(documents, history):
            reviewed_at = now - timedelta(hours=hours)
            document.update(reps=reps, lapses=lapses, success_streak=streak, last_grade=grade,
                            ewma_grade=float(grade), last_sent_at=reviewed_at, last_interaction_at=reviewed_at,
                            last_activity_at=reviewed_at)
    return user_fields, documents


async def apply_profile(cols: dict, user_service, user_id: int, words: list[str], profile: str,
                        now: datetime) -> tuple[int, int]:
    """Replace the user's words and record with `profile`'s: (words removed, words added)."""
    user_fields, documents = profile_documents(profile, user_id, words, now)
    stored_id = str(user_id)
    removed = (await cols["expression"].delete_many({"user_id": stored_id})).deleted_count
    await cols["users"].delete_one({"user_id": stored_id})
    await user_service.record_seen(user_id, "dev")  # the one creator of users
    if user_fields:
        await cols["users"].update_one({"user_id": stored_id}, {"$set": user_fields})
    if documents:
        await cols["expression"].insert_many(documents)
    return removed, len(documents)


async def seed(settings, env: dict, profile: str = "ready") -> None:
    """Indexes, then the dev user reset to `profile`."""
    from flashcard.composition import build_core, open_resources
    from flashcard.language import LanguageConfig
    from flashcard.utils.time import now_utc

    async with open_resources(settings) as resources:
        core = build_core(resources.cols, resources.http_client, settings, LanguageConfig.from_settings(settings))
        await core.expression_service.ensure_indexes()
        await core.user_service.ensure_indexes()
        removed, added = await apply_profile(resources.cols, core.user_service, env["user_id"],
                                             SEED_WORDS[env["language"]], profile, now_utc())
        print(f"Dev user reset to profile '{profile}': removed {removed} words, added {added} "
              f"(database {env['database']})")


# --- Tunnel mode: normal Telegram, a public https tunnel (cloudflared) to this laptop --------------------
# The tunnel reaches only the API on 127.0.0.1, which serves a production build of the Mini App: no Vite
# dev server, no source files, no dev init data. Init data older than 1 hour is refused. A leak check
# runs before the bot's menu button points at the tunnel, and the built files are re-checked every few
# seconds while it runs; any finding stops everything.

TUNNEL_INIT_DATA_MAX_AGE = 3600
DIST = ROOT / "miniapp" / "dist"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# No word boundary before the digits: inside a URL a token reads "bot123456:...".
BOT_TOKEN_SHAPE = re.compile(r"(?<![0-9])[0-9]{6,12}:[A-Za-z0-9_-]{30,}")
SIGNED_HASH = re.compile(r"hash=[0-9a-f]{64}")
# Paths a dev server or a careless static server could expose. The API must answer 404 or the app shell.
PROBE_PATHS = ("/.env", "/.env.local", "/.env.dev", "/src/telegram.ts", "/@vite/client", "/@fs/C:/Windows/win.ini",
               "/package.json", "/vite.config.ts", "/%2e%2e/flashcard-project/.env.dev")


def secret_values(env: dict) -> list[str]:
    """Strings that must never be served: tokens, keys, the local dev init data."""
    values = [env["token"], env["token"].partition(":")[2], env["groq_key"]]
    if FRONTEND_ENV.is_file():
        for line in FRONTEND_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{FRONTEND_VAR}=") and line.partition("=")[2]:
                values.append(line.partition("=")[2])
    return [value for value in values if value and len(value) >= 8]


def leaks_in(text: str, secrets: list[str]) -> list[str]:
    """What kind of secret `text` contains (kinds only, never the value)."""
    found = []
    if any(secret in text for secret in secrets):
        found.append("a dev secret value")
    if BOT_TOKEN_SHAPE.search(text):
        found.append("something shaped like a bot token")
    if SIGNED_HASH.search(text):
        found.append("signed init data")
    return found


def scan_dist(secrets: list[str]) -> list[str]:
    """Leaks in the built files, as 'file: kind' lines."""
    findings = []
    if not DIST.is_dir():
        return ["dist: the build is missing"]
    try:
        paths = sorted(DIST.rglob("*"))
    except FileNotFoundError:  # a --watch rebuild is emptying dist right now
        return ["dist: the build is being replaced"]
    for path in paths:
        if path.is_file():
            name = path.relative_to(DIST).as_posix()
            if path.name.startswith(".") or path.suffix in (".map", ".ts", ".tsx"):
                findings.append(f"{name}: a file that must not be served")
                continue
            try:
                text = path.read_bytes().decode("utf-8", errors="ignore")
            except (FileNotFoundError, PermissionError):
                # Removed or still being written by a rebuild: gone files are not served, and the next
                # scan (5 s later) reads the new one.
                continue
            findings += [f"{name}: {kind}" for kind in leaks_in(text, secrets)]
    return findings


def stop_process_tree(process: subprocess.Popen) -> None:
    """Stop a child and everything it started. On Windows npx.cmd runs cmd.exe -> node.exe, and
    terminate() would stop only cmd.exe, leaving `vite build --watch` running."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                       capture_output=True, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def find_npx() -> str | None:
    """npx; on Windows the .cmd launcher (a bare `npx` found there is a shell script)."""
    return shutil.which("npx.cmd") if sys.platform == "win32" else shutil.which("npx")


def build_frontend(watch: bool = False):
    """Production build without dev init data. watch=True returns the rebuilding process."""
    npx = find_npx()
    if npx is None:
        raise SetupError("npx not found: install Node.js")
    env = {**ORIGINAL_ENVIRON, "VITE_DEV_INIT_DATA": ""}
    command = [npx, "vite", "build", "--emptyOutDir"] + (["--watch"] if watch else [])
    if watch:
        return subprocess.Popen(command, cwd=ROOT / "miniapp", env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run(command, cwd=ROOT / "miniapp", env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SetupError("The Mini App build failed:\n" + result.stdout[-2000:] + result.stderr[-2000:])
    return None


def start_tunnel(port: int) -> tuple[subprocess.Popen, str]:
    """A cloudflared quick tunnel to 127.0.0.1:port and its public URL."""
    cloudflared = shutil.which("cloudflared")
    if cloudflared is None:
        raise SetupError("cloudflared not found: install it (scoop install cloudflared)")
    # http2 (TCP): QUIC over UDP is often slow or dropped on mobile and institutional networks.
    process = subprocess.Popen([cloudflared, "tunnel", "--no-autoupdate", "--protocol", "http2",
                                "--url", f"http://127.0.0.1:{port}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace")
    # The URL comes first; the tunnel works only once a connection to Cloudflare is registered.
    url, last_error = None, None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        line = process.stderr.readline()
        if not line and process.poll() is not None:
            break
        if " ERR " in line:
            last_error = line.split(" ERR ", 1)[1].strip()[:200]
        match = TUNNEL_URL.search(line)
        if match:
            url = match.group(0)
        if url and "Registered tunnel connection" in line:
            # Keep draining its log so the pipe never fills; the lines are not shown.
            threading.Thread(target=lambda: [None for _ in process.stderr], daemon=True).start()
            return process, url
    process.terminate()
    raise SetupError("cloudflared could not connect to Cloudflare within 90 seconds"
                     + (f" (cloudflared: {last_error})" if last_error else "")
                     + ". It needs outbound port 7844, which institutional networks often block: "
                       "use another network, such as your phone's hotspot. Quick tunnels are also rate limited: "
                       "wait a minute and retry.")


async def check_tunnel(base: str, env: dict, secrets: list[str]) -> list[str]:
    """Fetch the app through the public URL and confirm nothing leaks and sign-in is strict."""
    import httpx

    problems = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:

        async def get(url, **kwargs):
            """GET with 3 tries: a slow mobile network must not crash the check (it still fails closed)."""
            for attempt in range(3):
                try:
                    return await client.get(url, **kwargs)
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2)

        local = await client.get(f"http://{HOST}:{PORT}/")
        if local.status_code != 200:
            return [f"the API itself answers {local.status_code} for / (setup problem, not a leak)"]
        # Wait before the first lookup: asking for a brand-new hostname too early can cache "not found".
        await asyncio.sleep(5)
        index, last = None, "no answer"
        for _ in range(30):
            try:
                response = await client.get(base + "/")
                if response.status_code == 200:
                    index = response.text
                    break
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as error:
                last = type(error).__name__
            await asyncio.sleep(2)
        if index is None:
            return [f"the tunnel did not serve the app within a minute (last: {last})"]

        try:
            served = [f"/{path.relative_to(DIST).as_posix()}" for path in DIST.rglob("*") if path.is_file()]
            for path in ["/"] + served:
                response = await get(base + path)
                problems += [f"{path}: {kind}" for kind in leaks_in(response.text, secrets)]
            for path in PROBE_PATHS:
                response = await get(base + path)
                problems += [f"{path}: {kind}" for kind in leaks_in(response.text, secrets)]
                # Refused (400 from the server or the tunnel, 404) or the app shell is fine; anything else is not.
                if response.status_code not in (400, 404) and response.text != index:
                    problems.append(f"{path}: answered {response.status_code} with content")

            me = base + API_ME
            if (await get(me)).status_code != 401:
                problems.append("the API answered without sign-in")
            old = sign_init_data(env, auth_date=int(time.time()) - TUNNEL_INIT_DATA_MAX_AGE - 600)
            if (await get(me, headers={"Authorization": f"tma {old}"})).status_code != 401:
                problems.append("the API accepted init data older than 1 hour")
            fresh = sign_init_data(env)
            if (await get(me, headers={"Authorization": f"tma {fresh}"})).status_code != 200:
                problems.append("the API refused fresh init data (setup problem, not a leak)")
        except httpx.TransportError as error:
            problems.append(f"could not finish the check through the tunnel ({type(error).__name__}); "
                            "the network is too slow or dropped")
    return problems


async def set_dev_menu(env: dict, url: str | None) -> None:
    """Point the dev user's menu button at `url`, or back to the default. Normal Telegram, dev bot only."""
    from aiogram import Bot
    from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo
    from flashcard.telegram.session import build_ipv4_session

    bot = Bot(token=env["token"], session=build_ipv4_session())
    try:
        button = MenuButtonWebApp(text="Kartino", web_app=WebAppInfo(url=url)) if url else MenuButtonDefault()
        await bot.set_chat_menu_button(chat_id=env["user_id"], menu_button=button)
    finally:
        await bot.session.close()


async def run_tunnel(settings, env: dict) -> None:
    import logging

    import uvicorn
    from flashcard.miniapp.api import create_app
    from flashcard.telegram.bot import running_bot

    logging.getLogger("httpx").setLevel(logging.WARNING)  # the leak check makes many requests
    secrets = secret_values(env)
    findings = scan_dist(secrets)
    if findings:
        raise SetupError("Leak check failed in the build; nothing was started:\n  " + "\n  ".join(findings))

    server = uvicorn.Server(uvicorn.Config(create_app(settings), host=HOST, port=PORT, log_level="warning"))
    api = asyncio.create_task(server.serve())
    tunnel = watcher = None
    menu_set = False
    try:
        while not server.started:
            if api.done():
                api.result()
                raise SetupError("The API stopped during start-up")
            await asyncio.sleep(0.1)
        tunnel, base = start_tunnel(PORT)
        print(f"Tunnel up at {base}; checking it for leaks")
        problems = await check_tunnel(base, env, secrets)
        if problems:
            raise SetupError("Leak check failed through the tunnel; stopping:\n  " + "\n  ".join(problems))
        await set_dev_menu(env, base + "/")
        menu_set = True
        watcher = build_frontend(watch=True)

        async with running_bot(settings, "polling") as (_, telegram):
            print("Leak check passed. Open your dev bot in Telegram and tap Kartino. Edits rebuild in a few "
                  "seconds; close and reopen the Mini App to see them. Ctrl+C stops everything.")

            async def recheck():
                while True:
                    await asyncio.sleep(5)
                    found = scan_dist(secrets)
                    # A rebuild empties dist for a moment; only a real finding stops.
                    found = [line for line in found if not line.startswith("dist:")]
                    if found:
                        print("LEAK in a rebuild; stopping:\n  " + "\n  ".join(found))
                        return

            checker = asyncio.create_task(recheck())
            done, _ = await asyncio.wait({api, telegram.polling_task, checker}, return_when=asyncio.FIRST_COMPLETED)
            checker.cancel()
            for task in done:
                if task is not checker and not task.cancelled() and task.exception():
                    raise task.exception()
    finally:
        server.should_exit = True
        for process in (tunnel, watcher):
            if process is not None:
                stop_process_tree(process)
        if menu_set:  # the tunnel URL dies with this process
            try:
                await set_dev_menu(env, None)
            except Exception:  # noqa: BLE001 - a dead button is harmless; say so
                print("Could not reset the dev bot's menu button; it points at a dead tunnel URL.")
        await asyncio.gather(api, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="serve", choices=("serve", "seed", "init-data", "check", "tunnel"))
    parser.add_argument("--env-file", default=str(PROJECT / ".env.dev"), help="default: flashcard-project/.env.dev")
    parser.add_argument("--profile", choices=SEED_PROFILES, help="seed only: the dev user's state (default: ready)")
    parser.add_argument("--days-ahead", type=float, default=0.0,
                        help="run the app's clock this many days ahead (serve, tunnel, seed)")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    if args.profile and args.command != "seed":
        raise SetupError("--profile is for seed only")
    if args.days_ahead and args.command not in CLOCK_COMMANDS:
        raise SetupError(f"--days-ahead is for {', '.join(CLOCK_COMMANDS)} only")
    if not 0 <= args.days_ahead <= MAX_DAYS_AHEAD:  # also refuses nan and inf
        raise SetupError(f"--days-ahead must be between 0 and {MAX_DAYS_AHEAD}")
    env = load_env(Path(args.env_file), tunnel=args.command == "tunnel")
    if args.days_ahead:
        from flashcard.utils.time import shift_clock
        shift_clock(timedelta(days=args.days_ahead))
        print(f"The app's clock runs {args.days_ahead:g} day(s) ahead (sign-in uses the real time)")
    if args.command == "check":
        print(f"OK: language {env['language']}, database {env['database']} on loopback, dev user and keys present")
    elif args.command == "init-data":
        refresh_init_data(env)
    elif args.command == "tunnel":
        env["settings_extra"] = {"MINIAPP_STATIC_DIR": str(DIST),
                                 "MINIAPP_INIT_DATA_MAX_AGE_SECONDS": str(TUNNEL_INIT_DATA_MAX_AGE)}
        print("Building the Mini App (production build, no dev init data)...")
        build_frontend()
        try:
            with_settings(env, lambda settings: asyncio.run(run_tunnel(settings, env)))
        except KeyboardInterrupt:
            pass
    elif args.command == "seed":
        with_settings(env, lambda settings: asyncio.run(seed(settings, env, args.profile or "ready")))
    else:
        try:
            serve(env)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
