import logging
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aiogram.filters import CommandObject

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


@pytest.mark.parametrize(
    "args, expected",
    [
        ("web_fa_hero", "web_fa_hero"),
        ("web-nav", "web-nav"),
        (None, None),
        ("", None),
        ("web hero", None),
        ("x" * 65, None),
        ("web_hero\nforged line", None),
    ],
)
def test_start_source_accepts_only_telegram_payloads(args, expected):
    assert start.start_source(args) == expected


@pytest.mark.asyncio
async def test_start_logs_source_without_the_user(caplog):
    message = AsyncMock()
    message.from_user.id = 424242

    with caplog.at_level(logging.INFO, logger="flashcard"):
        await start.cmd_start(message, i18n=TEST_I18N, command=CommandObject(command="start", args="web_hero"))

    assert "source=web_hero" in caplog.text
    assert "424242" not in caplog.text
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_without_payload_logs_nothing(caplog):
    message = AsyncMock()

    with caplog.at_level(logging.INFO, logger="flashcard"):
        await start.cmd_start(message, i18n=TEST_I18N, command=CommandObject(command="start"))

    assert "source=" not in caplog.text
