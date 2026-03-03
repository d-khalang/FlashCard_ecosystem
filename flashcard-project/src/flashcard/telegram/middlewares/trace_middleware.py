import uuid
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, Update

from flashcard.schemas.trace import TraceData
from flashcard.utils.tracing import set_current_trace, clear_current_trace
from flashcard.services.trace_logger import get_trace_logger
from flashcard.utils.time import now_utc, iso_z

class TraceMiddleware(BaseMiddleware):
    """
    Middleware to wrap every Telegram update in a Trace.
    Initializes the contextvar, times the entire execution, 
    and flushes the final trace to the JSON file logger.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Determine basic context
        user_id = None
        user_name = None
        text = None
        update_type = "unknown"

        # If attached to dp.update, `event` is an Update object
        actual_event = event
        if isinstance(event, Update):
            if event.message:
                actual_event = event.message
                update_type = "message"
            elif event.callback_query:
                actual_event = event.callback_query
                update_type = "callback_query"

        # Now extract the info from the actual message/callback
        if isinstance(actual_event, Message):
            if actual_event.from_user:
                user_id = actual_event.from_user.id
                user_name = actual_event.from_user.username or actual_event.from_user.full_name
            text = actual_event.text or actual_event.caption
        elif isinstance(actual_event, CallbackQuery):
            if actual_event.from_user:
                user_id = actual_event.from_user.id
                user_name = actual_event.from_user.username or actual_event.from_user.full_name
            text = actual_event.data

        start_dt = now_utc()
        trace_id = str(uuid.uuid4())

        # Initialize the Trace object
        trace = TraceData(
            trace_id=trace_id,
            timestamp=iso_z(start_dt),
            user_id=user_id,
            user_name=user_name,
            update_type=update_type,
            text=text,
            spans=[] # Spans will be added by @observe decorators during execution
        )

        # Set it in the contextvar so child functions can access it
        token = set_current_trace(trace)
        data["trace_id"] = trace_id

        has_error = False
        error_msg = None

        try:
            # Continue the handler pipeline
            result = await handler(event, data)
            return result
        except Exception as e:
            has_error = True
            error_msg = str(e)
            # Preserve trace id for aiogram error handlers even if context/data propagation changes
            try:
                setattr(e, "trace_id", trace_id)
            except Exception:
                pass
            raise e
        finally:
            end_dt = now_utc()
            # Finalize metrics
            trace.end(start_dt, end_dt, has_error, error_msg)

            # Serialize down to JSON automatically via pydantic
            trace_json = trace.model_dump_json()

            # Pass string directly to the queue logger
            get_trace_logger().log_trace_json(trace_json)

            # Clean up context
            clear_current_trace(token)
