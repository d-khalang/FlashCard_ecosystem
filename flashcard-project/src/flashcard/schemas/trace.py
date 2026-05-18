from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime


class Span(BaseModel):
    """Represents a single step or 'node' in a trace (e.g., a function call)."""
    name: str = Field(description="Name of the function or step (e.g., 'LLMService.generate_expression_card')")
    start_time: str = Field(description="ISO 8601 timestamp when the span started")
    end_time: Optional[str] = Field(None, description="ISO 8601 timestamp when the span ended")
    latency_ms: Optional[float] = Field(None, description="Execution time in milliseconds")
    status: str = Field(default="ok", description="'ok' or 'error'")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Arguments passed to the function")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional structured span metadata")
    output: Any = Field(None, description="Return value or exception details")
    error: Optional[str] = Field(None, description="Error message if status is 'error'")


class TraceData(BaseModel):
    """Represents a full end-to-end execution of a request (e.g., a Telegram message)."""
    trace_id: str = Field(description="Unique UUID for this execution")
    timestamp: str = Field(description="ISO 8601 timestamp when the trace started")
    user_id: Optional[int] = Field(None, description="Telegram user ID, if known early on")
    user_name: Optional[str] = Field(None, description="Telegram user's full name or username")
    update_type: str = Field(description="Type of trigger (e.g., 'message', 'callback_query', 'scheduler')")
    text: Optional[str] = Field(None, description="The raw message text or callback data that triggered this trace")
    total_latency_ms: Optional[float] = Field(None, description="Total execution time in milliseconds")
    status: str = Field(default="success", description="'success' or 'error'")
    error: Optional[str] = Field(None, description="Global error message if the trace failed")
    spans: List[Span] = Field(default_factory=list, description="Ordered list of steps that occurred during execution")

    def end(self, start_dt: datetime, end_dt: datetime, has_error: bool = False, error_msg: str = None) -> None:
        """Helper to finalize trace metrics."""
        delta = end_dt - start_dt
        self.total_latency_ms = delta.total_seconds() * 1000
        if has_error:
            self.status = "error"
            self.error = error_msg
