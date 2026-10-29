from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from flashcard.telegram.handlers import start
from tests.helpers import TEST_I18N, TEST_LANGUAGE


@pytest.mark.asyncio
async def test_help_includes_verb_when_conjugation_enabled():
    message = AsyncMock()

    await start.cmd_help(message, language=replace(TEST_LANGUAGE, conjugation=True), i18n=TEST_I18N)

    help_text = message.answer.await_args.args[0]
    assert "/verb" in help_text


@pytest.mark.asyncio
async def test_help_omits_verb_when_conjugation_disabled():
    message = AsyncMock()

    await start.cmd_help(message, language=replace(TEST_LANGUAGE, conjugation=False), i18n=TEST_I18N)

    help_text = message.answer.await_args.args[0]
    assert "/verb" not in help_text
