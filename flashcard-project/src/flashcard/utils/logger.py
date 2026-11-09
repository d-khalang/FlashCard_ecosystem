import logging
import sys
from urllib.parse import quote

APP_LOGGER_NAME = "flashcard"
ACCESS_LOGGER_NAME = "uvicorn.access"
MASKED_PATH = "<webhook>"


def _use_utf8(stream) -> None:
    """Switch a text stream to UTF-8; unencodable characters are replaced, never raised."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        # e.g. a stream that already has buffered output; keep its encoding.
        pass


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

        # 1. Configure the specific Application Logger
        # This logger will handle everything under "flashcard.*"
        # INFO until an entry point calls configure_log_level with LOG_LEVEL.
        app_logger = logging.getLogger(APP_LOGGER_NAME)
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False  # Isolate from Root Logger

        # Windows consoles default to cp1252, which cannot encode the ⚡ in our format.
        _use_utf8(sys.stdout)

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

        # 2. Configure Root Logger (Third-party libraries)
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


def configure_log_level(level: str) -> None:
    """Set the app logger's level (`LOG_LEVEL`); entry points call this at startup."""
    FlashCardLogger.setup()
    logging.getLogger(APP_LOGGER_NAME).setLevel(getattr(logging, level.upper(), logging.INFO))


class _MaskPathFilter(logging.Filter):
    """Replaces a request path in an access-log record's arguments; never drops the record."""

    def __init__(self, path: str):
        super().__init__()
        # uvicorn logs the percent-encoded path, followed by the query string.
        self._paths = {path.rstrip("/"), quote(path).rstrip("/")}

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(MASKED_PATH if self._is_masked(arg) else arg for arg in record.args)
        return True

    def _is_masked(self, arg: object) -> bool:
        return isinstance(arg, str) and arg.partition("?")[0].rstrip("/") in self._paths


def mask_access_log_path(path: str) -> None:
    """Keep `path` out of uvicorn's access log; the last call in a process wins."""
    access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
    for existing in [f for f in access_logger.filters if isinstance(f, _MaskPathFilter)]:
        access_logger.removeFilter(existing)
    access_logger.addFilter(_MaskPathFilter(path))


def get_logger(name: str) -> logging.Logger:
    """
    Convenience function to get a logger. 
    This is the primary compatible entry point for the codebase.
    """
    return FlashCardLogger.get_logger(name)


async def notify_admin_with_trace(bot, text: str, trace_id: str | None = None, *, admin_id: int):
    """
    Sends a message to the bot Admin, safely checking if there is an active Trace ID.
    If yes, injects it at the bottom to allow easy crossing-referencing with JSON lines logs.
    """
    from flashcard.utils.tracing import get_current_trace
    
    trace_id_str = ""
    try:
        resolved_trace_id = trace_id
        if not resolved_trace_id:
            trace = get_current_trace()
            if trace and hasattr(trace, 'trace_id'):
                resolved_trace_id = trace.trace_id
        if resolved_trace_id:
            trace_id_str = f"\n\n[Trace ID: {resolved_trace_id}]"
    except Exception as e:
        pass # Failsafe so the alert itself never crashes
        
    final_text = f"{text}{trace_id_str}"
    
    try:
        await bot.send_message(chat_id=admin_id, text=final_text, parse_mode="HTML")
    except Exception as e:
        get_logger(__name__).error(f"Failed to send admin notification: {e}")
