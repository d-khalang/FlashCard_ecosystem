# 🇮🇹 FlashCard Ecosystem

An AI-powered Telegram bot for learning Italian through spaced repetition flashcards.

Send any Italian word or expression → get an AI-generated explanation card → save it → receive scheduled reviews with spaced repetition.

## Features

- 📝 **Flashcard Creation** — Send any Italian word/expression and get an AI-generated study card
- 🔄 **Spaced Repetition** — Automatic review scheduling based on your performance (0–5 grading)
- 📖 **Story Generation** — Generate stories using your saved vocabulary
- 🔤 **Verb Conjugation** — Look up any Italian verb's conjugation tables
- 📥 **Bulk Import** — Import multiple words at once
- ⚙️ **User Settings** — Customize language, level, review interval
- 📊 **Dual Review Mode** — Review in both directions (Italian → English and English → Italian)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Bot Framework | [aiogram 3](https://docs.aiogram.dev/) (async Telegram bot) |
| API Layer | [FastAPI](https://fastapi.tiangolo.com/) |
| AI/LLM | [Google Gemini](https://ai.google.dev/) (structured JSON output) |
| Database | [MongoDB](https://www.mongodb.com/) (async via pymongo) |
| Verb Data | Custom WordReference scraper |
| Deployment | Docker Compose + Caddy (auto-HTTPS, custom domain) |

## Repository Structure

```
FlashCard-ecosystem/
├── flashcard-project/       # Main bot application
│   ├── src/flashcard/       # Python package
│   ├── docs/                # Documentation
│   └── Dockerfile
├── WR_scraper/              # WordReference conjugation scraper
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
| [Contributing](flashcard-project/docs/contributing.md) | How to add features, conventions |

## License

[MIT](LICENSE)
