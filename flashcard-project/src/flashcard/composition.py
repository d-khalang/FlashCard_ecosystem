"""
Composition root (docs/bot-architecture-refactor.md, #10).

The one place that opens the shared clients and wires services and use cases.
Every runtime (FastAPI + Telegram, dev polling, later the Mini App) starts here,
so the core is built the same way everywhere and no client is opened twice.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from flashcard.app.collection import CollectionUseCases
from flashcard.app.creation import CreationUseCases
from flashcard.app.quota import QuotaPolicy
from flashcard.app.review import ReviewUseCases
from flashcard.app.settings import SettingsUseCases
from flashcard.app.story import StoryUseCases
from flashcard.app.verb import VerbUseCases
from flashcard.db.mongo import close_mongo_on_client, init_and_get_mongo
from flashcard.language import LanguageConfig
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.http_client import close_http_client_on_client, init_and_get_http_client
from flashcard.services.language_validation import get_language_validator
from flashcard.services.llm.llm import LLMService
from flashcard.services.review_state import ReviewStateStore
from flashcard.services.user import UserService
from flashcard.services.verb import VerbService


@dataclass(frozen=True)
class Resources:
    mongo_client: object
    cols: dict
    http_client: object


@asynccontextmanager
async def open_resources(settings):
    """Open Mongo and the HTTP client once; close each once, in reverse order."""
    mongo_client, _, cols = await init_and_get_mongo(settings)
    try:
        http_client = await init_and_get_http_client()
        try:
            yield Resources(mongo_client=mongo_client, cols=cols, http_client=http_client)
        finally:
            await close_http_client_on_client(http_client)
    finally:
        await close_mongo_on_client(mongo_client)


@dataclass(frozen=True)
class Core:
    language: LanguageConfig
    expression_service: ExpressionService
    user_service: UserService
    consumption_service: ConsumptionService
    review_state: ReviewStateStore
    verb_service: Optional[VerbService]
    llm_service: LLMService
    language_validator: object
    quota: QuotaPolicy
    review_use_cases: ReviewUseCases
    creation_use_cases: CreationUseCases
    settings_use_cases: SettingsUseCases
    story_use_cases: StoryUseCases
    # None when conjugation is disabled; the verb router is not included then.
    verb_use_cases: Optional[VerbUseCases]
    collection_use_cases: CollectionUseCases

    def handler_data(self, logger_bot) -> dict:
        """What Telegram handlers and middlewares receive: use cases, not services."""
        return {
            "logger_bot": logger_bot,
            "language": self.language,
            # TraceMiddleware records every user as seen (the only upsert on `users`).
            "user_service": self.user_service,
            "review_use_cases": self.review_use_cases,
            "creation_use_cases": self.creation_use_cases,
            "settings_use_cases": self.settings_use_cases,
            "story_use_cases": self.story_use_cases,
            "verb_use_cases": self.verb_use_cases,
            "collection_use_cases": self.collection_use_cases,
        }


def build_core(cols: dict, http_client, settings, language: LanguageConfig) -> Core:
    """
    The only place that hands out collections: each service gets just its own,
    so no service can reach another's data. Services get the instance's language
    from here, never from global settings.
    """
    expression_service = ExpressionService(expressions=cols["expression"])
    user_service = UserService(users=cols["users"], defaults=language.user_defaults)
    consumption_service = ConsumptionService(users=cols["users"])
    review_state = ReviewStateStore(users=cols["users"])
    verb_service = (
        VerbService(conjugations=cols["conjugation"], http_client=http_client)
        if language.conjugation
        else None
    )
    llm_service = LLMService(learning_language_name=language.name)
    language_validator = get_language_validator(language)
    quota = QuotaPolicy(consumption_service, settings)
    return Core(
        language=language,
        expression_service=expression_service,
        user_service=user_service,
        consumption_service=consumption_service,
        review_state=review_state,
        verb_service=verb_service,
        llm_service=llm_service,
        language_validator=language_validator,
        quota=quota,
        review_use_cases=ReviewUseCases(
            expression_service=expression_service,
            user_service=user_service,
            quota=quota,
            llm_service=llm_service,
            review_state=review_state,
            user_defaults=language.user_defaults,
        ),
        creation_use_cases=CreationUseCases(
            expression_service=expression_service,
            user_service=user_service,
            quota=quota,
            llm_service=llm_service,
            review_state=review_state,
            language_validator=language_validator,
        ),
        settings_use_cases=SettingsUseCases(user_service=user_service),
        story_use_cases=StoryUseCases(
            expression_service=expression_service,
            user_service=user_service,
            quota=quota,
            llm_service=llm_service,
        ),
        verb_use_cases=(
            VerbUseCases(verb_service=verb_service, consumption_service=consumption_service)
            if verb_service is not None else None
        ),
        collection_use_cases=CollectionUseCases(
            expression_service=expression_service,
            user_service=user_service,
            quota=quota,
            llm_service=llm_service,
            review_state=review_state,
            language_validator=language_validator,
        ),
    )
