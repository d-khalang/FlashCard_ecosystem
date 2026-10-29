from aiogram.filters import Filter
from aiogram.types import Message

from flashcard.services.i18n import I18nService


class ButtonText(Filter):
    """
    Matches a reply-keyboard button by its locale keys. The text is looked up per
    update in the injected `i18n`, so it always matches what the keyboards show.
    """

    def __init__(self, *keys: str):
        self.keys = keys

    async def __call__(self, message: Message, i18n: I18nService) -> bool:
        return message.text is not None and any(message.text == i18n.get(key) for key in self.keys)
