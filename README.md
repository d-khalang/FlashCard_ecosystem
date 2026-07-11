# FlashCard Ecosystem

An AI-powered Telegram bot ecosystem for learning languages through spaced repetition flashcards. Italian is the default out-of-the-box configuration.

Send any target-language word or expression → get an AI-generated explanation card → save it → receive scheduled reviews with spaced repetition. The current production Italian deployment is live at [kartino.it](https://kartino.it).

## Features

- 📝 **Flashcard Creation** — Send any configured learning-language word/expression and get an AI-generated study card
- 🔄 **Spaced Repetition** — Automatic review scheduling based on your performance (0–5 grading)
- 📖 **Story Generation** — Generate stories using your saved vocabulary
- 🔤 **Verb Conjugation** — Optional conjugation lookup for languages with a configured conjugator service
- 📥 **Bulk Import** — Import multiple words at once
- ⚙️ **User Settings** — Customize language, level, review interval
- 📊 **Dual Review Mode** — Review in both directions between the learning language and translation language

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Bot Framework | [aiogram 3](https://docs.aiogram.dev/) (async Telegram bot) |
| API Layer | [FastAPI](https://fastapi.tiangolo.com/) |
| AI/LLM | [Google Gemini](https://ai.google.dev/) (structured JSON output) |
| Database | [MongoDB](https://www.mongodb.com/) (async via pymongo) |
| Verb Data | Optional [Offline Italian Conjugation API](it-conjugator-api) (SQLite + Kaikki/Wiktionary data) |
| Deployment | Docker Compose + Caddy (auto-HTTPS, custom domain) |

## Repository Structure

```
FlashCard-ecosystem/
├── flashcard-project/       # Main bot application
│   ├── src/flashcard/       # Python package
│   ├── docs/                # Documentation
│   └── Dockerfile
├── web/                     # [Private Submodule] Landing page & brand assets
├── it-conjugator-api/       # [Public Submodule] Optional offline Italian conjugation API
├── docker-compose.yml       # Multi-service orchestration
└── .env.example             # Environment variable template
```

## Quick Start

### Local Development

```bash
# 1. Clone
git clone https://github.com/your-org/FlashCard-ecosystem.git
cd FlashCard-ecosystem

# 2. Setup
cp .env.example .env          # Fill in your tokens and config
# For non-Docker local development, point MONGO_URI at your local MongoDB.
cd flashcard-project
python -m venv venv
venv\Scripts\activate          # Windows
pip install -e .

# 3. Run (polling mode — no webhook needed)
flashcard-bot-dev-poll
```

### Docker

```bash
cp .env.example .env  # Fill in your values
docker compose up --build
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](flashcard-project/docs/architecture.md) | System overview, data flows, package structure |
| [Services](flashcard-project/docs/services.md) | Service layer API reference |
| [Handlers](flashcard-project/docs/handlers.md) | Bot commands, router order, UI layer |
| [Configuration](flashcard-project/docs/configuration.md) | Environment variables, Docker services |
| [CI/CD](docs/cicd.md) | GitHub Actions pipelines and deployment workflow |
| [Contributing](flashcard-project/docs/contributing.md) | How to add features, conventions |

## License

[MIT](LICENSE)
