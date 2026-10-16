"""
Tests for /story at the Telegram entry point: saved words -> LLM story -> paragraph/translation pairs.

Flag: -l asks for a longer story.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.story import StoryUseCases
from flashcard.schemas.story import StoryParagraph, StoryResponse
from flashcard.schemas.user import UserAPIConfig, UserDB, UserTier
from flashcard.services.i18n import i18n
from flashcard.telegram.handlers import story
from flashcard.telegram.ui.story import format_story_messages


USER_ID = 888
STORY = StoryResponse(paragraphs=[
    StoryParagraph(learning_text="C'era una volta.", translation="Once upon a time."),
    StoryParagraph(learning_text="Fine.", translation="The end."),
])


def _user(**overrides) -> UserDB:
    fields = {"user_id": str(USER_ID), "tier": UserTier.normal, "primary_language": "fa", "target_level": "B1"}
    fields.update(overrides)
    return UserDB(**fields)


def _deps(words=("andare", "fare"), *, user=None, can_generate=True, story_response=STORY):
    expression_service = MagicMock()
    expression_service.get_all_expressions = AsyncMock(side_effect=lambda user_id: list(words))

    user_service = MagicMock()
    user_service.get_user = AsyncMock(return_value=user or _user())
    user_service.can_generate_story = MagicMock(return_value=can_generate)
    user_service.story_limit = MagicMock(return_value=3)

    consumption_service = MagicMock()
    consumption_service.increment = AsyncMock()

    llm_service = MagicMock()
    llm_service.generate_story = (
        AsyncMock(side_effect=story_response) if isinstance(story_response, Exception)
        else AsyncMock(return_value=story_response))

    return SimpleNamespace(expression_service=expression_service, user_service=user_service,
                           consumption_service=consumption_service, llm_service=llm_service)


async def _run(d, text="/story"):
    message = MagicMock()
    message.text = text
    message.from_user.id = USER_ID
    message.answer = AsyncMock()
    use_cases = StoryUseCases(expression_service=d.expression_service, user_service=d.user_service,
                              consumption_service=d.consumption_service, llm_service=d.llm_service)
    await story.cmd_story(message, story_use_cases=use_cases)
    return message


def _sent(message) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


class TestStory:

    async def test_story_is_sent_as_paragraph_and_spoiler_pairs(self):
        d = _deps()
        message = await _run(d)

        assert _sent(message) == [i18n.get("commands.story.writing", count=2),
                                  *format_story_messages(STORY, target_lang="fa")]
        assert _sent(message)[2] == "🇮🇷 <tg-spoiler>Once upon a time.</tg-spoiler>"

    async def test_llm_gets_words_translation_language_level_and_default_length(self):
        d = _deps()
        await _run(d)

        d.llm_service.generate_story.assert_awaited_once_with(
            words=["andare", "fare"], target_lang="fa", target_level="B1", story_length="6-10 sentences")

    @pytest.mark.parametrize("text", ["/story -l", "/story foo -l"])
    async def test_l_flag_asks_for_a_longer_story(self, text):
        d = _deps()
        await _run(d, text=text)

        assert d.llm_service.generate_story.await_args.kwargs["story_length"] == "10-16 sentences"

    @pytest.mark.parametrize("text", ["/story -long", "/story -L", "/story l"])
    async def test_other_arguments_keep_the_default_length(self, text):
        d = _deps()
        await _run(d, text=text)

        assert d.llm_service.generate_story.await_args.kwargs["story_length"] == "6-10 sentences"

    async def test_story_is_counted_after_sending(self):
        d = _deps()
        await _run(d)

        d.consumption_service.increment.assert_awaited_once_with(USER_ID, "stories_generated", uses_own_key=False)

    async def test_own_key_is_counted_separately(self):
        d = _deps(user=_user(api_config=UserAPIConfig(provider="gemini", api_key="k")))
        await _run(d)

        d.user_service.can_generate_story.assert_called_once()
        assert d.user_service.can_generate_story.call_args.kwargs == {"uses_own_key": True}
        d.consumption_service.increment.assert_awaited_once_with(USER_ID, "stories_generated", uses_own_key=True)


class TestStoryWords:

    async def test_no_saved_words_stops_before_anything_else(self):
        d = _deps(words=())
        message = await _run(d)

        assert _sent(message) == [i18n.get("commands.story.no_expressions")]
        d.user_service.get_user.assert_not_awaited()
        d.llm_service.generate_story.assert_not_awaited()

    async def test_up_to_80_words_are_all_used_in_order(self):
        words = [f"parola{i}" for i in range(80)]
        d = _deps(words=words)
        await _run(d)

        assert d.llm_service.generate_story.await_args.kwargs["words"] == words

    async def test_more_than_80_words_uses_a_random_80(self):
        words = [f"parola{i}" for i in range(200)]
        d = _deps(words=words)
        message = await _run(d)

        used = d.llm_service.generate_story.await_args.kwargs["words"]
        assert len(used) == 80 and len(set(used)) == 80 and set(used) <= set(words)
        assert _sent(message)[0] == i18n.get("commands.story.writing", count=80)


class TestStoryQuota:

    async def test_over_quota_tells_the_user_and_skips_the_llm(self):
        d = _deps(can_generate=False)
        message = await _run(d)

        assert _sent(message)[-1] == i18n.get("messages.errors.quota_exceeded", type="story", tier="normal", limit=3)
        d.llm_service.generate_story.assert_not_awaited()
        d.consumption_service.increment.assert_not_awaited()

    async def test_over_quota_gets_only_the_quota_message(self):
        d = _deps(can_generate=False)
        message = await _run(d)

        assert _sent(message) == [i18n.get("messages.errors.quota_exceeded", type="story", tier="normal", limit=3)]


class TestStoryFailures:

    async def test_llm_error_propagates_and_is_not_counted(self):
        # The global error handler tells the user.
        d = _deps(story_response=RuntimeError("llm down"))

        with pytest.raises(RuntimeError):
            await _run(d)
        d.consumption_service.increment.assert_not_awaited()

    async def test_empty_story_shows_error_and_is_not_counted(self):
        d = _deps(story_response=StoryResponse(paragraphs=[]))
        message = await _run(d)

        assert _sent(message) == [i18n.get("commands.story.writing", count=2),
                                  i18n.get("commands.story.generation_error")]
        d.consumption_service.increment.assert_not_awaited()
