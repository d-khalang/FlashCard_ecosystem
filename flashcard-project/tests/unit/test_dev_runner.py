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
    env_file.write_text("KARTINO_DEV_BOT_TOKEN=123:abc extra words\nKARTINO_DEV_USER_ID=5 x\nKARTINO_DEV_GROQ_KEY=k\n"
                        "KARTINO_DEV_MONGO_URI=mongodb://127.0.0.1:1,evil.example.com:2/\n")

    with pytest.raises(SystemExit) as error:
        runner.load_env(env_file)

    assert "evil.example.com" not in str(error.value) and "123:abc" not in str(error.value)
