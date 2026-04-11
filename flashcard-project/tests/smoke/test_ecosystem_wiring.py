from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href":
                self.links.append(value)


def test_docker_compose_defines_expected_services_and_healthchecks():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service_name in ["flashcard-bot", "wr-scraper", "mongo", "caddy"]:
        assert f"{service_name}:" in compose
    assert "http://localhost:8000/health" in compose
    assert "http://localhost:8000/health" in compose
    assert "mongosh" in compose


def test_caddyfile_routes_webhook_and_health_to_flashcard_bot():
    caddyfile = (ROOT / "caddy" / "Caddyfile").read_text(encoding="utf-8")

    assert "bot.{$DOMAIN}" in caddyfile
    assert "reverse_proxy flashcard-bot:8000" in caddyfile
    assert "path {$WEBHOOK_PATH}" in caddyfile
    assert "handle /health" in caddyfile
    assert "respond 404" in caddyfile


def test_ci_workflow_runs_unit_and_integration_layers():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pytest tests/unit" in ci
    assert "pytest tests/integration" in ci
    assert "pytest tests/integration tests/smoke" in ci


def test_deploy_workflow_validates_production_env_and_uses_compose():
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

    assert "test -f .env.prod" in deploy
    assert "docker compose --env-file .env.prod up -d --build" in deploy
    assert "WEBHOOK_BASE" in deploy


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[3] / "web" / "index.html").exists(),
    reason="web submodule not checked out",
)
def test_web_index_contains_expected_public_links():
    parser = AnchorParser()
    parser.feed((ROOT / "web" / "index.html").read_text(encoding="utf-8"))

    assert parser.links
    assert any("telegram" in link.lower() or "t.me" in link.lower() for link in parser.links)


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[3] / "web" / "index.html").exists(),
    reason="web submodule not checked out",
)
def test_web_assets_and_scripts_exist():
    web_dir = ROOT / "web"

    assert (web_dir / "index.html").exists()
    assert (web_dir / "style.css").exists()
    assert (web_dir / "script.js").exists()
    assert any((web_dir / "images").iterdir())


def test_repo_docs_call_out_runtime_testing_and_cicd():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "CI/CD" in readme
    assert "flashcard-project/docs/architecture.md" in readme
