import socket

from aiogram.client.session.aiohttp import AiohttpSession

from flashcard.utils.logger import get_logger


def build_ipv4_session() -> AiohttpSession:
    """Build an aiogram session that forces IPv4.

    Docker's default bridge network has no IPv6 routing, so aiohttp
    may occasionally attempt an IPv6 connection to api.telegram.org
    that silently hangs until the OS timeout (20-60 s).  Pinning to
    AF_INET eliminates the issue entirely.
    """
    session = AiohttpSession()
    # Inject IPv4 family into the lazy connector initialization
    # Note: Modern aiogram (3.x) doesn't take 'connector' in __init__, so we touch internal state
    session._connector_init["family"] = socket.AF_INET

    get_logger(__name__).info("Telegram session: forcing IPv4 (AF_INET)")
    return session
