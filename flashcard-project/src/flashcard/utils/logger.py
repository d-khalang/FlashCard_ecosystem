import logging
import sys
from flashcard.settings import settings

APP_LOGGER_NAME = "flashcard"

class FlashCardLogger:
    """
    Centralized logger configuration for the application.
    Separates application logging from third-party libraries to interpret
    logs clearly and avoid conflicts with libraries like aiogram.
    """
    _initialized = False

    @classmethod
    def setup(cls):
        """
        Configures the main application logger and ensures root logger behaves reasonably.
        """
        if cls._initialized:
            return

        # 1. Determine Log Level
        level_str = settings.LOG_LEVEL.upper()
        log_level = getattr(logging, level_str, logging.INFO)

        # 2. Configure the specific Application Logger
        # This logger will handle everything under "flashcard.*"
        app_logger = logging.getLogger(APP_LOGGER_NAME)
        app_logger.setLevel(log_level)
        app_logger.propagate = False  # Isolate from Root Logger

        # Add Handler if not present
        if not app_logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            # Use a clean, distinct format for our app
            formatter = logging.Formatter(
                fmt="[%(asctime)s] ⚡ %(levelname)s | %(name)s | %(message)s",
                datefmt="%H:%M:%S"
            )
            handler.setFormatter(formatter)
            app_logger.addHandler(handler)

        # 3. Configure Root Logger (Third-party libraries)
        # External libs (like aiogram) will log to Root. We ensure it has a handler.
        # We use a standard format for them.
        logging.basicConfig(
            level=logging.INFO, # Default for libs
            format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            stream=sys.stdout
        )

        cls._initialized = True

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Returns a configured logger.
        If the name starts with the app prefix, it inherits the custom config.
        """
        cls.setup()
        return logging.getLogger(name)

    @classmethod
    def get_child(cls, name: str) -> logging.Logger:
        """
        Explicitly creates a child of the main APP logger.
        Usage: get_child("services.verb") -> "flashcard.services.verb"
        """
        cls.setup()
        return logging.getLogger(APP_LOGGER_NAME).getChild(name)


def get_logger(name: str) -> logging.Logger:
    """
    Convenience function to get a logger. 
    This is the primary compatible entry point for the codebase.
    """
    return FlashCardLogger.get_logger(name)
