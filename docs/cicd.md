# CI/CD Guide (GitHub Actions)

## Overview

This repository uses:

- CI workflow: `.github/workflows/ci.yml`
- Release workflow: `.github/workflows/release.yml`

CI and release builds run on GitHub-hosted runners. Production deployment will
move to the private `kartino-deploy` repository, which pins immutable image
digests and owns the production Compose topology.

## CI

`ci.yml` runs on push to `main` and pull requests.

Checks:

- Python unit, integration, and smoke tests
- Docker build check for:
  - `flashcard-project/Dockerfile`
  - `it-conjugator-api/Dockerfile`

CI injects test-safe values directly in the workflow. It does not use
production secrets. Third-party actions are pinned to immutable commit SHAs.

## Container Releases

Publishing a GitHub Release triggers `release.yml`. The workflow:

- Verifies the tag matches `flashcard-project/pyproject.toml`.
- Runs the complete Python test suite.
- Publishes version and full commit-SHA tags to GHCR.
- Publishes no mutable `latest` tag.
- Generates an SBOM and signed build provenance.
- Attaches each immutable image digest to the GitHub Release.

See [Releasing Container Images](../flashcard-project/docs/releasing.md) for the
operator procedure and resulting image names.

## Deployment Boundary

This public repository has no production deployment workflow, production
credentials, or access to a production runner. It produces tested container
images only. The private `kartino-deploy` repository owns production Compose,
runtime secrets, image digest updates, rollout, and rollback.
