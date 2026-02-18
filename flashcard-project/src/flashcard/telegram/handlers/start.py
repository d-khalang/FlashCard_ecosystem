from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from flashcard.services.i18n import i18n
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    # Retrieve welcome message from I18n service
    welcome_text = i18n.get("commands.start.welcome")
    await message.answer(welcome_text)
    #TODO: translations and detailed explanations be added by buttons
    # also video, possibly in reply markup


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(i18n.get("commands.help.message"))
    await message.reply(i18n.get("commands.help.reply"))

