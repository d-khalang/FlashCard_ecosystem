"""
Shadow writes for the review-state migration.

While legacy fields (has_pending, pending_message_id) stay authoritative, the new
users.current_review is written alongside them. A failure there is logged and
never breaks the user's send, grade or remove.
"""
from typing import Awaitable

from flashcard.utils.logger import get_logger

logger = get_logger(__name__)


async def shadow_write(write: Awaitable, what: str) -> None:
    try:
        await write
    except Exception:
        logger.warning("Shadow write failed: %s", what, exc_info=True)
