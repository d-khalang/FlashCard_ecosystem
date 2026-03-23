import uvicorn
import argparse
import sys
import warnings
from flashcard.settings import settings

import asyncio
from flashcard.telegram.bot import init_telegram_without_fastapi, close_telegram_without_fastapi

def main():
    """Entry point for production run"""
    uvicorn.run(
        "flashcard.api.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=False
    )

def dev():
    """Entry point for development run with reload"""
    uvicorn.run(
        "flashcard.api.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True
    )

async def _run_poll():
    resources = await init_telegram_without_fastapi(settings)
    try:
        # Keep the script running by awaiting the polling task
        await resources["polling_task"]
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await close_telegram_without_fastapi(resources)

def main_poll():
    """
    Deprecated production polling alias.

    Production should always run the FastAPI app so health endpoints remain
    available to Docker and external monitors.
    """
    warnings.warn(
        "flashcard-bot-poll is deprecated. Use flashcard-bot with "
        "TELEGRAM_DELIVERY_MODE=polling instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    main()

def dev_poll():
    """Entry point for lightweight local development polling run."""
    asyncio.run(_run_poll())

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "dev":
            dev()
        elif cmd == "main_poll":
            main_poll()
        elif cmd == "dev_poll":
            dev_poll()
    else:
        main()
