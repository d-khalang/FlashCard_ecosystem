from unittest.mock import AsyncMock, patch

import pytest

from flashcard.telegram.handlers import start


@pytest.mark.asyncio
async def test_help_includes_verb_when_conjugation_enabled():
    message = AsyncMock()

    with patch("flashcard.telegram.handlers.start.settings.ENABLE_CONJUGATION", True):
        await start.cmd_help(message)

    help_text = message.answer.await_args.args[0]
    assert "/verb" in help_text


@pytest.mark.asyncio
async def test_help_omits_verb_when_conjugation_disabled():
    message = AsyncMock()

    with patch("flashcard.telegram.handlers.start.settings.ENABLE_CONJUGATION", False):
        await start.cmd_help(message)

    help_text = message.answer.await_args.args[0]
    assert "/verb" not in help_text
