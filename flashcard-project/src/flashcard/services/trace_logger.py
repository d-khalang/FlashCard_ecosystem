import logging
import queue
import os
import atexit
from logging.handlers import TimedRotatingFileHandler, QueueHandler, QueueListener

class TraceLogger:
    """
    Asynchronous file logger for execution traces.
    Uses a QueueHandler to ensure that tracing never blocks the main async event loop.
    A background thread (QueueListener) picks up log records and writes them to a rotating file.
    """
    _instance = None

    def __init__(self, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.filename = os.path.join(log_dir, "traces.jsonl")
        
        # Configure the underlying file handler
        # Rotates at midnight, keeps 14 days of backups
        self.file_handler = TimedRotatingFileHandler(
            filename=self.filename,
            when="midnight",
            interval=1,
            backupCount=14,
            encoding="utf-8"
        )
        
        # Do not format the message, we expect pre-formatted JSON strings
        self.file_handler.setFormatter(logging.Formatter("%(message)s"))

        # Create a queue of unlimited size (or define a maxsize if memory constrained)
        self.log_queue = queue.Queue()
        
        # The QueueHandler pushes records to the queue (non-blocking in main thread)
        self.queue_handler = QueueHandler(self.log_queue)
        
        # Setup a dedicated logger instance
        self.logger = logging.getLogger("execution_tracer")
        self.logger.setLevel(logging.INFO)
        # Remove any existing handlers to prevent duplicates during reloads
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.addHandler(self.queue_handler)

        # The listener runs in a background thread and pops from the queue
        self.listener = QueueListener(
            self.log_queue, 
            self.file_handler,
            respect_handler_level=True
        )
        self.listener.start()
        
        # Ensure the listener stops cleanly on shutdown
        atexit.register(self.shutdown)

    @classmethod
    def get_instance(cls) -> "TraceLogger":
        if cls._instance is None:
            cls._instance = TraceLogger()
        return cls._instance

    def log_trace_json(self, trace_json: str):
        """Immediately queues a JSON string to be written to the file."""
        self.logger.info(trace_json)

    def shutdown(self):
        """Stops the background thread and flushes remaining logs."""
        if hasattr(self, 'listener') and self.listener:
            try:
                self.listener.stop()
                self.file_handler.close()
            except Exception:
                pass

# Global instance getter
def get_trace_logger() -> TraceLogger:
    return TraceLogger.get_instance()
