"""
Story use case: write a short story from the user's saved words.

Callers own presentation and command parsing (e.g. the "long" flag).
"""
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union

from flashcard.app.quota import QuotaExceeded
from flashcard.app.types import UserId
from flashcard.schemas.story import StoryResponse
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.llm.llm import LLMService
from flashcard.services.user import UserService

# Bounds prompt size; above this a random sample is used.
MAX_STORY_WORDS = 80
SHORT_STORY = "6-10 sentences"
LONG_STORY = "10-16 sentences"

# Awaited with the number of words once the story is about to be written.
WritingNotifier = Callable[[int], Awaitable[None]]


@dataclass(frozen=True)
class Story:
    story: StoryResponse
    translation_language: str


@dataclass(frozen=True)
class NoWords:
    pass


@dataclass(frozen=True)
class EmptyStory:
    """The LLM answered without paragraphs; not counted as usage."""
    pass


StoryResult = Union[Story, NoWords, EmptyStory, QuotaExceeded]


class StoryUseCases:
    def __init__(
        self,
        expression_service: ExpressionService,
        user_service: UserService,
        consumption_service: ConsumptionService,
        llm_service: LLMService,
    ):
        self.expressions = expression_service
        self.users = user_service
        self.consumption = consumption_service
        self.llm = llm_service

    async def write(self, user_id: UserId, long: bool = False,
                    on_writing: Optional[WritingNotifier] = None) -> StoryResult:
        words = await self.expressions.get_all_expressions(user_id)
        if not words:
            return NoWords()

        user = await self.users.get_user(user_id)
        uses_own_key = user.api_config is not None
        if not self.users.can_generate_story(user, uses_own_key=uses_own_key):
            return QuotaExceeded(tier=user.tier.value, limit=self.users.story_limit(user))

        if len(words) > MAX_STORY_WORDS:
            words = random.sample(words, MAX_STORY_WORDS)
        if on_writing is not None:
            await on_writing(len(words))

        story = await self.llm.generate_story(
            words=words,
            target_lang=user.primary_language,
            target_level=user.target_level,
            story_length=LONG_STORY if long else SHORT_STORY,
        )
        if not story.paragraphs:
            return EmptyStory()

        await self.consumption.increment(user_id, "stories_generated", uses_own_key=uses_own_key)
        return Story(story=story, translation_language=user.primary_language)
