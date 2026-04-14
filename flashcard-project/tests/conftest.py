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
    "BOT_TOKEN": "123456:test-token",
    "LOGGER_BOT_TOKEN": "123456:test-logger",
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


import pytest

@pytest.fixture(autouse=True)
def clear_aiogram_routers_state():
    """
    aiogram Routers strictly forbid being attached to more than one Dispatcher.
    Since our routers are import-level singletons, tests that repeatedly call
    build_bot_dispatcher() will crash. This cleans the internal _parent_router 
    state before every test.
    """
    from flashcard.telegram.handlers import (
        user_settings, 
        feedback, 
        reply_commands,
        start,
        review,
        verb,
        story,
        collection,
        inline_remove,
        unknown,
        creation,
        errors
    )
    
    routers = [
        user_settings.router, feedback.router, reply_commands.router, 
        start.router, review.router, verb.router, story.router, 
        collection.router, inline_remove.router, unknown.router, 
        creation.router, errors.router
    ]
    
    for r in routers:
        r._parent_router = None
