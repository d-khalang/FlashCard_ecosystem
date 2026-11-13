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

    for service_name in ["flashcard-bot", "conjugator", "mongo", "caddy"]:
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


def test_ci_workflow_runs_the_browser_tests_and_fails_when_they_cannot_run():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pytest tests/browser" in ci
    assert 'KARTINO_REQUIRE_BROWSER: "1"' in ci
    assert "playwright install --with-deps webkit chromium" in ci


def test_release_workflow_verifies_and_publishes_immutable_images():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "types:" in release and "published" in release
    # A release runs exactly the CI checks, which must fail (not skip) without MongoDB.
    assert "uses: ./.github/workflows/ci.yml" in release
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in ci and 'KARTINO_REQUIRE_MONGO: "1"' in ci
    assert "ghcr.io" in release
    assert "type=semver" in release
    assert "type=sha" in release
    assert "subject-digest" in release
    assert "gh release upload" in release


def test_a_final_release_reuses_the_verified_candidates_images():
    """A final tag builds nothing: it re-tags the images of the release candidate on its commit."""
    import yaml

    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))["jobs"]

    assert jobs["verify"]["if"] == jobs["publish"]["if"] == "needs.version.outputs.kind == 'rc'"
    assert jobs["promote"]["if"] == "needs.version.outputs.kind == 'final'"
    # A candidate is built only after the live contract tests pass, and they may not skip.
    assert "contract" in jobs["publish"]["needs"] and jobs["contract"]["if"] == jobs["publish"]["if"]
    assert jobs["contract"]["env"]["KARTINO_REQUIRE_CONTRACT"] == "1"
    assert "pytest tests/contract" in "\n".join(step.get("run", "") for step in jobs["contract"]["steps"])
    promote = "\n".join(step.get("run", "") for step in jobs["promote"]["steps"])
    assert "imagetools create" in promote and "build-push-action" not in str(jobs["promote"])
    assert '[[ "$tagged" == "$digest" ]]' in promote  # the new tag must be the same image
    check = "\n".join(step.get("run", "") for step in jobs["version"]["steps"])
    assert '"$sha" == "$tag_sha"' in check  # only a candidate on the tagged commit counts
    assert "workflow_dispatch" in check and "Only a final release can be promoted by hand" in check
    # The candidate is built with the final version, so the promoted image is labelled right.
    metadata = [step for step in jobs["publish"]["steps"] if step.get("id") == "metadata"][0]
    assert "org.opencontainers.image.version=${{ needs.version.outputs.base }}" in metadata["with"]["labels"]


def test_public_repo_has_no_production_deploy_workflow():
    assert not (ROOT / ".github" / "workflows" / "deploy.yml").exists()


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
