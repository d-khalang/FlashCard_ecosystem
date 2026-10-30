"""
Unit tests for StoryUseCases.write: the story contract, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.quota import QuotaExceeded
from flashcard.app.story import (
    LONG_STORY, MAX_STORY_WORDS, SHORT_STORY, EmptyStory, NoWords, Story, StoryUseCases,
)
from flashcard.schemas.story import StoryParagraph, StoryResponse
from flashcard.schemas.user import UserTier
from tests.helpers import make_quota, make_user

STORY = StoryResponse(paragraphs=[StoryParagraph(learning_text="Ciao.", translation="Hi.")])


def _use_cases(words=("andare", "fare"), *, exceeded=None, story=STORY, user=None):
    expressions = MagicMock()
    expressions.get_all_expressions = AsyncMock(return_value=list(words))

    users = MagicMock()
    users.get_user = AsyncMock(return_value=user or make_user(
        user_id=888, tier=UserTier.normal, primary_language="de", target_level="A2"))

    consumption = MagicMock()
    consumption.increment = AsyncMock()

    llm = MagicMock()
    llm.generate_story = AsyncMock(return_value=story)

    use_cases = StoryUseCases(expression_service=expressions, user_service=users,
                              quota=make_quota(consumption, exceeded), llm_service=llm)
    return use_cases, consumption, llm


class TestWrite:

    async def test_story_is_written_counted_and_returned_with_translation_language(self):
        use_cases, consumption, llm = _use_cases()

        assert await use_cases.write(888) == Story(story=STORY, translation_language="de")
        llm.generate_story.assert_awaited_once_with(
            words=["andare", "fare"], target_lang="de", target_level="A2", story_length=SHORT_STORY)
        consumption.increment.assert_awaited_once_with(888, "stories_generated", uses_own_key=False)

    async def test_long_story(self):
        use_cases, _, llm = _use_cases()
        await use_cases.write(888, long=True)

        assert llm.generate_story.await_args.kwargs["story_length"] == LONG_STORY

    async def test_writing_is_announced_with_the_word_count_before_the_llm_call(self):
        use_cases, _, llm = _use_cases(words=[f"w{i}" for i in range(200)])
        calls = []

        async def on_writing(count):
            calls.append((count, llm.generate_story.await_count))

        await use_cases.write(888, on_writing=on_writing)

        assert calls == [(MAX_STORY_WORDS, 0)]

    async def test_words_above_the_limit_are_a_random_sample_without_mutating_the_input(self):
        words = [f"w{i}" for i in range(200)]
        use_cases, _, llm = _use_cases(words=words)
        await use_cases.write(888)

        used = llm.generate_story.await_args.kwargs["words"]
        assert len(set(used)) == MAX_STORY_WORDS and set(used) <= set(words)


class TestWriteStops:

    async def test_no_words(self):
        use_cases, consumption, llm = _use_cases(words=())
        on_writing = AsyncMock()

        assert await use_cases.write(888, on_writing=on_writing) == NoWords()
        on_writing.assert_not_awaited()
        llm.generate_story.assert_not_awaited()

    async def test_quota_exceeded_is_not_announced(self):
        use_cases, consumption, llm = _use_cases(exceeded=QuotaExceeded(tier="normal", limit=3))
        on_writing = AsyncMock()

        assert await use_cases.write(888, on_writing=on_writing) == QuotaExceeded(tier="normal", limit=3)
        on_writing.assert_not_awaited()
        llm.generate_story.assert_not_awaited()
        consumption.increment.assert_not_awaited()

    async def test_empty_story_is_not_counted(self):
        use_cases, consumption, _ = _use_cases(story=StoryResponse(paragraphs=[]))

        assert await use_cases.write(888) == EmptyStory()
        consumption.increment.assert_not_awaited()

    async def test_llm_error_propagates_uncounted(self):
        use_cases, consumption, llm = _use_cases()
        llm.generate_story.side_effect = RuntimeError("down")

        with pytest.raises(RuntimeError):
            await use_cases.write(888)
        consumption.increment.assert_not_awaited()
