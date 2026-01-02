# Flashcard Project

This is the Python-based Flashcard Bot core service, replacing the previous n8n workflow.

## Structure
- `src/flashcard`: Main package
- `src/flashcard/api`: FastAPI layer (webhooks, health)
- `src/flashcard/telegram`: Aiogram bot layer

## Running Locally
1. `pip install -e .`
2. `cp ../.env.example .env` (and fill it)
3. `flashcard-bot-dev`

## Running via Docker
The root `docker-compose.yml` builds this service.
- `docker compose up --build flashcard-bot`

## Configuration
See `.env.example` in the root.
