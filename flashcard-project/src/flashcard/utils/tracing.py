import contextvars
import functools
import inspect
from typing import Any, Callable, Dict, Optional
from datetime import datetime

from flashcard.schemas.trace import Span, TraceData
from flashcard.utils.time import now_utc, iso_z
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

# The ContextVar that holds the currently active trace for the request
current_trace_var: contextvars.ContextVar[Optional[TraceData]] = contextvars.ContextVar("current_trace", default=None)

def get_current_trace() -> Optional[TraceData]:
    """Retrieves the active trace from the current context."""
    return current_trace_var.get()

def set_current_trace(trace: TraceData) -> contextvars.Token:
    """Sets the active trace. Usually called by middleware at the start of a request."""
    return current_trace_var.set(trace)

def clear_current_trace(token: contextvars.Token) -> None:
    """Clears the trace back to its previous state."""
    current_trace_var.reset(token)

def finalize_trace(
    trace: TraceData,
    token: contextvars.Token,
    start_dt: datetime,
    has_error: bool = False,
    error_msg: Optional[str] = None,
) -> None:
    """Finalize, persist, and clear trace context."""
    from flashcard.services.trace_logger import get_trace_logger

    end_dt = now_utc()
    trace.end(start_dt, end_dt, has_error, error_msg)
    get_trace_logger().log_trace_json(trace.model_dump_json())
    clear_current_trace(token)

def observe(name: Optional[str] = None, include_output: bool = True) -> Callable:
    """
    Decorator to wrap a function to automatically record a Span in the current TraceData.
    Captures inputs, outputs, errors, and latency.
    """
    def decorator(func: Callable) -> Callable:
        # Determine the name of the span
        span_name = name if name else f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            trace = get_current_trace()
            if not trace:
                # Tracing is not active in this context, just run the function
                return await func(*args, **kwargs)

            # Helper for rough serialization
            def _serialize(obj: Any) -> Any:
                if hasattr(obj, "model_dump"):
                    return obj.model_dump(mode="json")
                if hasattr(obj, "dict"):
                    return obj.dict()
                try:
                    import json
                    json.dumps(obj)
                    return obj
                except (TypeError, OverflowError):
                    return f"<{type(obj).__name__}>"

            # 1. Capture Inputs
            inputs = {}
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                
                for k, v in bound_args.arguments.items():
                    if k in ('self', 'cls'):
                        continue
                    inputs[k] = _serialize(v)
            except Exception as e:
                inputs = {"_capture_error": str(e)}

            start_dt = now_utc()
            
            span = Span(
                name=span_name,
                start_time=iso_z(start_dt),
                inputs=inputs
            )

            # Add it to the trace immediately to preserve order
            span_idx = len(trace.spans)
            trace.spans.append(span)

            # 2. Execute Function
            try:
                result = await func(*args, **kwargs)
                
                # 3. Capture Output
                end_dt = now_utc()
                delta_ms = (end_dt - start_dt).total_seconds() * 1000
                
                # Update the span (since we have a reference to the list item)
                span.end_time = iso_z(end_dt)
                span.latency_ms = delta_ms
                span.status = "ok"
                
                if include_output:
                    span.output = _serialize(result)
                else:
                    span.output = {"_info": "omitted by include_output=False"}

                return result

            except Exception as e:
                # 4. Capture Error
                end_dt = now_utc()
                delta_ms = (end_dt - start_dt).total_seconds() * 1000
                
                span.end_time = iso_z(end_dt)
                span.latency_ms = delta_ms
                span.status = "error"
                span.error = str(e)
                
                # We do not suppress the error, we re-raise it
                raise e

        # Basic synchronous wrapper check based on asyncio.iscoroutinefunction is sometimes unreliable if decorated prior,
        # but in this ecosystem, virtually all services are async. We assume async.
        # If sync is needed, we'd add logic here to check `inspect.iscoroutinefunction(func)`.
        if not inspect.iscoroutinefunction(func):
            # fallback for sync functions
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # (Duplicate of async logic, omitted here for brevity; assume mostly async for this bot)
                logger.warning("Sync function decorated with @observe. This is not recommended.\n\n")
                return func(*args, **kwargs)
            return sync_wrapper
            
        return async_wrapper
    return decorator
