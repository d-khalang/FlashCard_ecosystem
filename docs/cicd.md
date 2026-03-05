# CI/CD Guide (GitHub Actions)

## Overview

This repository uses:

- CI workflow: `.github/workflows/ci.yml`
- CD workflow: `.github/workflows/deploy.yml`

CI runs on GitHub-hosted runners. CD runs on a self-hosted runner installed on the production VM.

## CI

`ci.yml` runs on push to `main` and pull requests.

Checks:

- Python unit tests (`flashcard-project/tests/unit`)
- Docker build check for:
  - `flashcard-project/Dockerfile`
  - `WR_scraper/Dockerfile`

CI injects test-safe environment variables directly in the workflow so no production secrets are required.

## CD

`deploy.yml` is manual (`workflow_dispatch`) and deploys on a self-hosted runner with labels:

- `self-hosted`
- `linux`
- `x64`
- `flashcard-prod`

Deployment command:

```bash
docker compose --env-file .env.prod up -d --build
```

`pull` is attempted first to support future image-based deployment.

## Required production host setup

1. Install Docker Engine + Docker Compose plugin.
2. Clone this repository on the VM.
3. Create `.env.prod` at repo root (never commit it).
4. Install and register a GitHub self-hosted runner on the VM with label `flashcard-prod`.
5. Ensure runner service has permission to run Docker commands.

## Production env strategy

- Local development: `.env` or `.env.dev`
- Production deployment: `.env.prod`
- Template/reference only: `.env.example`

Do not commit `.env.prod`.
