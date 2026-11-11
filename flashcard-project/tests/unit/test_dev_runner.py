"""The dev runner's safety checks (it must never reach a server that is not on this machine)."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "miniapp_dev", Path(__file__).resolve().parents[2] / "dev" / "miniapp_dev.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.mark.parametrize("uri", [
    "mongodb://127.0.0.1:27019/?directConnection=true", "mongodb://localhost", "mongodb://[::1]:27017/db",
    "mongodb://user:pw@127.0.0.1:1,localhost:2/db", "mongodb://LOCALHOST:27017",
])
def test_loopback_uris_are_accepted(uri):
    assert runner.all_hosts_are_loopback(uri)


@pytest.mark.parametrize("uri", [
    "mongodb://db.example.com:27017", "mongodb://127.0.0.1:27017,db.example.com:27017/x",
    "mongodb://db.example.com,127.0.0.1/x", "mongodb://127.0.0.1@db.example.com/x",
    "mongodb://localhost:1,10.0.0.5:2,[::1]:3", "mongodb+srv://127.0.0.1/x", "http://localhost", "127.0.0.1",
    "mongodb://", "mongodb://[::2]:27017",
])
def test_any_other_host_in_the_list_refuses_the_whole_uri(uri):
    assert not runner.all_hosts_are_loopback(uri)


def test_the_token_is_the_first_word_and_values_stay_out_of_errors(tmp_path):
    env_file = tmp_path / "e.env"
    env_file.write_text("KARTINO_EN_SHADOW_BOT_TOKEN=123:abc extra words\nKARTINO_DEV_USER_ID=5 x\nKARTINO_DEV_GROQ_KEY=k\n"
                        "KARTINO_DEV_MONGO_URI=mongodb://127.0.0.1:1,evil.example.com:2/\n")

    with pytest.raises(SystemExit) as error:
        runner.load_env(env_file)

    assert "evil.example.com" not in str(error.value) and "123:abc" not in str(error.value)


def _env_file(tmp_path, text):
    path = tmp_path / "e.env"
    path.write_text(text)
    return path


# --- Tunnel mode: shadow bots only, nothing secret served ----------------------------------------------

BASE = "KARTINO_DEV_USER_ID=5\nKARTINO_DEV_GROQ_KEY=k\n"


def test_the_language_picks_its_shadow_bot(tmp_path):
    both = "KARTINO_EN_SHADOW_BOT_TOKEN=111:en\nKARTINO_IT_SHADOW_BOT_TOKEN=222:it\n" + BASE

    assert runner.load_env(_env_file(tmp_path, both))["token"] == "111:en"
    assert runner.load_env(_env_file(tmp_path, both + "KARTINO_DEV_LANGUAGE=it\n"))["token"] == "222:it"


def test_a_production_bot_id_is_refused_in_every_mode(tmp_path):
    env_file = _env_file(tmp_path, "KARTINO_EN_SHADOW_BOT_TOKEN=999:secretpart\nKARTINO_PROD_BOT_IDS=111, 999\n" + BASE)

    for tunnel in (False, True):
        with pytest.raises(SystemExit) as error:
            runner.load_env(env_file, tunnel=tunnel)
        assert "production bot" in str(error.value) and "secretpart" not in str(error.value)


def test_tunnel_mode_requires_the_production_id_list(tmp_path):
    env_file = _env_file(tmp_path, "KARTINO_EN_SHADOW_BOT_TOKEN=123:abc\n" + BASE)

    assert runner.load_env(env_file)["token"] == "123:abc"
    with pytest.raises(SystemExit) as error:
        runner.load_env(env_file, tunnel=True)
    assert "KARTINO_PROD_BOT_IDS" in str(error.value)
    ok = _env_file(tmp_path, "KARTINO_EN_SHADOW_BOT_TOKEN=123:abc\nKARTINO_PROD_BOT_IDS=111\n" + BASE)
    assert runner.load_env(ok, tunnel=True)["token"] == "123:abc"


@pytest.mark.parametrize("text, kind", [
    ("x=1;const k='groq-secret-key-123';", "a dev secret value"),
    ("fetch('/bot1234567:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/getMe')", "something shaped like a bot token"),
    ("auth_date=1&hash=" + "a" * 64, "signed init data"),
])
def test_leaks_are_named_by_kind_never_by_value(text, kind):
    found = runner.leaks_in(text, ["groq-secret-key-123"])

    assert found == [kind]
    assert "groq-secret-key-123" not in " ".join(found)


def test_clean_build_output_has_no_leaks():
    assert runner.leaks_in("location.hash='#top';const a=12:30;", ["groq-secret-key-123"]) == []


def test_the_build_scan_flags_secrets_and_files_that_must_not_be_served(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>ok</html>")
    (tmp_path / "assets" / "app.js").write_text("const t='groq-secret-key-123'")
    (tmp_path / "assets" / "app.js.map").write_text("{}")
    (tmp_path / ".env").write_text("A=1")
    monkeypatch.setattr(runner, "DIST", tmp_path)

    findings = runner.scan_dist(["groq-secret-key-123"])

    assert sorted(findings) == sorted([".env: a file that must not be served", "assets/app.js: a dev secret value",
                                       "assets/app.js.map: a file that must not be served"])


def test_signed_init_data_can_be_backdated_for_the_age_check():
    env = {"token": "123:abc", "user_id": 5}

    old = runner.sign_init_data(env, auth_date=1000)

    assert "auth_date=1000" in old


def test_a_file_removed_mid_rebuild_does_not_stop_the_scan(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>ok</html>")
    (tmp_path / "gone.js").write_text("x")
    monkeypatch.setattr(runner, "DIST", tmp_path)
    real_read = runner.Path.read_bytes

    def flaky_read(path):
        if path.name == "gone.js":
            raise FileNotFoundError(path)
        return real_read(path)

    monkeypatch.setattr(runner.Path, "read_bytes", flaky_read)

    assert runner.scan_dist(["groq-secret-key-123"]) == []
