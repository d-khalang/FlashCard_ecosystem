"""
The language-change confirmation uses the localized 'primary'/'secondary' label.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flashcard.app.settings import SettingsUseCases
from flashcard.services.i18n import i18n
from flashcard.telegram.handlers import user_settings
from flashcard.telegram.handlers.user_settings import SettingsPrompts
from tests.helpers import make_user


def _message(text):
    message = MagicMock()
    message.text = text
    message.from_user.id = 444
    message.reply = AsyncMock()
    message.answer = AsyncMock()
    return message


def _deps(state_name):
    state = MagicMock()
    state.get_state = AsyncMock(return_value=state_name)
    state.clear = AsyncMock()
    user_service = MagicMock()
    user_service.set_primary_language = AsyncMock()
    user_service.set_secondary_language = AsyncMock()
    user_service.get_user = AsyncMock(return_value=make_user(user_id="444"))
    return state, user_service


@pytest.mark.parametrize("locale, prompt, label", [
    ("en", SettingsPrompts.waiting_primary_lang, "Primary"),
    ("en", SettingsPrompts.waiting_secondary_lang, "Secondary"),
    ("it", SettingsPrompts.waiting_primary_lang, "principale"),
    ("it", SettingsPrompts.waiting_secondary_lang, "secondaria"),
])
async def test_confirmation_uses_localized_language_label(locale, prompt, label):
    state, user_service = _deps(prompt.state)
    message = _message("English")

    with patch.object(i18n, "default_lang", locale):
        await user_settings.answer_setting_prompt(
            message, state=state, settings_use_cases=SettingsUseCases(user_service=user_service))
        expected = i18n.get("commands.settings.prompts.success_lang", type=label, lang="English", flag="🇬🇧")

    message.reply.assert_awaited_once_with(expected)
    setting = "primary_language" if prompt == SettingsPrompts.waiting_primary_lang else "secondary_language"
    getattr(user_service, f"set_{setting}").assert_awaited_once_with(444, "en")
