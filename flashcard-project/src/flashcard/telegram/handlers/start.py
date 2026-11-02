from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from flashcard.services.i18n import I18nService
from flashcard.language import LanguageConfig
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


def _conjugation_help_line(i18n: I18nService, language: LanguageConfig) -> str:
    if not language.conjugation:
        return ""
    return i18n.get("commands.help.conjugation_line")


@router.message(CommandStart())
async def cmd_start(message: Message, i18n: I18nService):
    # Retrieve welcome message from I18n service
    welcome_text = i18n.get("commands.start.welcome")
    await message.answer(welcome_text)
    #TODO: translations and detailed explanations be added by buttons
    # also video, possibly in reply markup


@router.message(Command("help"))
async def cmd_help(message: Message, language: LanguageConfig, i18n: I18nService):
    await message.answer(
        i18n.get(
            "commands.help.message",
            conjugation_help=_conjugation_help_line(i18n, language),
        )
    )
    await message.reply(i18n.get("commands.help.reply"))

