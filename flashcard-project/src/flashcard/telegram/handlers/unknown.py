from aiogram import Router, F
from aiogram.types import Message

from flashcard.services.i18n import I18nService

router = Router()


# Unknown commands - must be registered AFTER all domain command routers
@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message, i18n: I18nService):
    """
    Handle unknown commands.
    """
    await message.answer(i18n.get("commands.unknown.message"))
