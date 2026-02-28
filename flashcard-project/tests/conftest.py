"""
Shared test fixtures for the FlashCard test suite.

pytest automatically discovers and uses this file for all tests
under the tests/ directory — no import needed.
"""
import os

# Prevent settings.py from crashing during tests by providing
# required env vars with dummy values.
# This block MUST run before any flashcard module is imported.
_TEST_ENV = {
    "BOT_TOKEN": "test:token",
    "LOGGER_BOT_TOKEN": "test:logger",
    "ADMIN_ID": "0",
    "WEBHOOK_BASE": "https://test.example.com",
    "WEBHOOK_PATH": "/webhook",
    "WEBHOOK_SECRET": "test-secret",
    "MONGO_URI": "mongodb://localhost:27017",
    "MONGO_DB": "test_db",
    "COLLECTION_USERS": "users",
    "COLLECTION_EXPRESSION": "expression",
    "COLLECTION_CONJUGATION": "conjugation",
    "SCRAPER_API_KEY": "test-key",
    "SCRAPER_URL": "http://localhost",
    "SCRAPER_PORT": "5000",
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)
