import uvicorn
import argparse
import sys
import warnings
from flashcard.settings import get_setting
from flashcard.utils.logger import configure_log_level

import asyncio
from flashcard.telegram.bot import running_bot

def main():
    """Entry point for production run"""
    uvicorn.run(
        "flashcard.api.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=get_setting().PORT,
        reload=False
    )

def dev():
    """Entry point for development run with reload"""
    uvicorn.run(
        "flashcard.api.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=get_setting().PORT,
        reload=True
    )

async def _run_poll():
    settings = get_setting()
    configure_log_level(settings.LOG_LEVEL)
    async with running_bot(settings, "polling") as (_, telegram):
        try:
            # Keep the script running by awaiting the polling task
            await telegram.polling_task
        except (KeyboardInterrupt, SystemExit):
            pass

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
