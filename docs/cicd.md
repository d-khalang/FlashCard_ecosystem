# CI/CD Guide (GitHub Actions)

## Overview

- CI: `.github/workflows/ci.yml` (checks on every pull request and push to `main`)
- Release: `.github/workflows/release.yml` (candidate build, promotion)
- Dependency updates: `.github/dependabot.yml`

CI and release builds run on GitHub-hosted runners. Production deployment lives in
the private `kartino-deploy` repository, which pins immutable image digests and
owns the production Compose topology.

## CI

`ci.yml` runs on pull requests and on push to `main`. `release.yml` also calls it
(`workflow_call`), so a release candidate passes exactly the same checks.

| Job | What it checks |
| --- | --- |
| `lint` | `ruff check src tests dev` (pyflakes + bugbear rules only) |
| `types` | `mypy` over `src/`, with a baseline of known-bad modules |
| `unit-tests` | Python unit, integration and smoke tests, with a MongoDB service |
| `miniapp` | Mini App: `npm test` and `npm run build` |
| `browser-tests` | Built Mini App in WebKit (iPhone) and Chromium (Android) against the real API, MongoDB and fakes (`tests/browser`) |
| `audit` | Lock files match `pyproject.toml`; `pip-audit`; `npm audit` |
| `docker-build-check` | Builds the bot, conjugator and Mini App images |

Required checks on `main`: `unit-tests`, `miniapp`, `browser-tests`,
`docker-build-check`, plus `lint`, `types` and `audit` once added to the ruleset.

Details:

- **MongoDB**: tests need it. CI sets `KARTINO_REQUIRE_MONGO=1`, so a missing
  database fails the run instead of skipping tests (locally they skip). The service
  is `mongo:7.0`, not 8.0: GitHub runners run Linux 6.19+, where MongoDB 8 refuses
  to start (SERVER-121912).
- **Browser tests** set `KARTINO_REQUIRE_BROWSER=1`; failures upload screenshots
  and traces as the `browser-test-failures` artifact (7 days).
- **Secrets**: CI uses test-safe values written in the workflow, no production
  secrets.
- **Concurrency**: a new push to a pull request cancels that PR's running check.
  A push to `main` never cancels the previous commit's run.
- **Actions** are pinned by commit SHA, with the version in a comment.

### Static checks

- `ruff` rules: `E4 E7 E9 F B` (see `[tool.ruff]` in `flashcard-project/pyproject.toml`).
  No style or formatting rules.
- `mypy` has a baseline: modules with errors are listed under
  `[[tool.mypy.overrides]]` and skipped. All other modules, and every new one, are
  checked. Fix a module, then remove it from the list. Never add one to get a
  change through.
- Run both locally from `flashcard-project/`: `ruff check src tests dev` and `mypy`.

## Reproducible installs

- `flashcard-project/requirements.txt`: locked runtime dependencies, with hashes.
- `flashcard-project/requirements-dev.txt`: the same plus the `dev` extra.
- CI and both Dockerfiles install with `pip install --require-hashes -r ...`, then
  `pip install --no-deps` for the project itself.
- Python 3.12, all platforms (`--universal`).
- `pyproject.toml` keeps the version ranges and the comments explaining the capped
  packages. The lock records what was resolved. The `audit` job fails if they drift.

Regenerate after changing dependencies in `pyproject.toml` (needs
[uv](https://docs.astral.sh/uv/)), from `flashcard-project/`:

```bash
uv pip compile pyproject.toml --universal --python-version 3.12 --generate-hashes -o requirements.txt
uv pip compile pyproject.toml --extra dev --universal --python-version 3.12 --generate-hashes -o requirements-dev.txt
```

To upgrade everything, add `--upgrade` to both commands.

The Mini App uses `miniapp/package-lock.json` (`npm ci`).

## Base images

Docker base images in `flashcard-project/Dockerfile`, `miniapp/Dockerfile` and the
CI MongoDB service are pinned by digest (`image:tag@sha256:...`), with the tag in a
comment. Dependabot proposes digest bumps. The conjugator image comes from the
`it-conjugator-api` submodule and is not pinned here.

## Dependency audit

The `audit` job fails the build on:

- `pip-audit` on `requirements.txt` (runtime packages): any known vulnerability.
  It has no severity filter.
- `npm audit --omit=dev --audit-level=high` in `miniapp/`: production packages,
  high and above.

Fix by upgrading the package. Do not remove the check to get green.

## Dependabot

`.github/dependabot.yml`: weekly, one grouped pull request per ecosystem: pip
(`flashcard-project`), npm (`miniapp`), docker (`flashcard-project`, `miniapp`) and
github-actions. Merge them like any other pull request; CI decides.

## Container Releases

Images are built once, for a release candidate, and re-tagged for the final release.

### Release candidate (`vX.Y.Z-rc.N`, published as a pre-release)

`release.yml` runs these jobs:

1. `Validate release version`: tag format, package version, pre-release flag.
2. `Verify release`: calls `ci.yml` on the tagged commit (all jobs above).
3. `Live contract tests`: `tests/contract` against Groq, edge-tts and the conjugator
   API (needs the secret `CONTRACT_GROQ_API_KEY`).
4. `Publish <image>` for `flashcard-bot`, `it-conjugator` and `flashcard-miniapp`:
   builds, pushes version and full commit SHA tags to GHCR, with an SBOM and signed
   build provenance, and attaches `<image>-digest.txt` to the pre-release.

No mutable `latest` tag is published.

### Final release (`vX.Y.Z`)

`Promote release candidate` builds nothing and runs no tests. It finds the highest
`vX.Y.Z-rc.N` on the same commit, adds the `X.Y.Z` tag to each candidate image,
checks that the tag names the same digest, and attaches the candidate's digest
files to the final release. A final tag on a commit without a candidate fails.

It can be re-run by hand (Actions, `Publish Release Images`, Run workflow) with the
final tag.

See [Releasing Container Images](../flashcard-project/docs/releasing.md) for the
operator procedure.

## Deployment Boundary

This public repository has no production deployment workflow, production
credentials, or access to a production runner. It produces tested container
images only. The private `kartino-deploy` repository owns production Compose,
runtime secrets, image digest updates, rollout, and rollback.
