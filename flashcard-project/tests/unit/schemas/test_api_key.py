import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flashcard.schemas.api_key import load_api_keys
from flashcard.services.llm.llm_key import LLMKeyProvider


@pytest.fixture(autouse=True)
def clear_api_key_cache():
    load_api_keys.cache_clear()
    yield
    load_api_keys.cache_clear()


def _valid_config():
    return {
        "core": [
            {"name": "primary", "api_key": "test-key", "provider": "google"}
        ],
        "reminder": [],
        "users": {},
    }


def test_loads_api_keys_from_external_file(tmp_path):
    key_file = tmp_path / "llm_key.json"
    key_file.write_text(json.dumps(_valid_config()), encoding="utf-8")

    config = load_api_keys(key_file)

    assert config.core[0].name == "primary"
    assert config.core[0].api_key == "test-key"


def test_provider_accepts_external_key_file(tmp_path):
    key_file = tmp_path / "llm_key.json"
    key_file.write_text(json.dumps(_valid_config()), encoding="utf-8")

    provider = LLMKeyProvider(key_file=key_file)

    assert provider.get_core_key("primary") == "test-key"


def test_provider_uses_configured_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "llm_key.json"
    key_file.write_text(json.dumps(_valid_config()), encoding="utf-8")
    monkeypatch.setattr(
        "flashcard.services.llm.llm_key.settings.LLM_KEY_FILE",
        str(key_file),
    )

    provider = LLMKeyProvider()

    assert provider.get_core_key("primary") == "test-key"


def test_missing_external_file_reports_configured_path(tmp_path):
    key_file = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError) as exc_info:
        load_api_keys(key_file)

    assert str(key_file) in str(exc_info.value)


def test_invalid_external_json_is_rejected(tmp_path):
    key_file = tmp_path / "llm_key.json"
    key_file.write_text("{not-json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_api_keys(key_file)


def test_invalid_external_schema_is_rejected(tmp_path):
    key_file = tmp_path / "llm_key.json"
    key_file.write_text(json.dumps({"core": []}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_api_keys(key_file)


def test_packaged_resource_remains_the_default(monkeypatch, tmp_path):
    package_root = tmp_path / "flashcard"
    resource_dir = package_root / "resources"
    resource_dir.mkdir(parents=True)
    (resource_dir / "llm_key.json").write_text(
        json.dumps(_valid_config()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "flashcard.schemas.api_key.files",
        lambda package: package_root,
    )

    config = load_api_keys()

    assert config.core[0].api_key == "test-key"


def test_public_example_file_matches_the_api_key_schema():
    project_root = Path(__file__).parents[3]
    example_file = project_root / "config" / "llm_key.example.json"

    config = load_api_keys(example_file)

    assert config.core[0].provider == "google"
    assert config.core[0].api_key == "replace-with-your-api-key"
