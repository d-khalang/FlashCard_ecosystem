import pytest
import asyncio
from datetime import datetime

from flashcard.schemas.trace import TraceData
from flashcard.utils.tracing import set_current_trace, observe, get_current_trace, clear_current_trace
from flashcard.utils.time import now_utc, iso_z
from flashcard.services.trace_logger import get_trace_logger

# Dummy async function to test @observe
@observe(name="dummy_func")
async def dummy_func(a: int, b: int) -> int:
    await asyncio.sleep(0.01)
    return a + b

@observe(name="error_func")
async def error_func():
    raise ValueError("Test error in tracing")

@pytest.mark.asyncio
async def test_tracing_capture():
    trace = TraceData(
        trace_id="test-trace-123",
        timestamp=iso_z(now_utc()),
        update_type="test"
    )
    token = set_current_trace(trace)

    res = await dummy_func(1, 2)
    assert res == 3
    
    current = get_current_trace()
    assert current is not None
    assert len(current.spans) == 1
    
    span = current.spans[0]
    assert span.name == "dummy_func"
    assert span.inputs == {"a": 1, "b": 2}
    assert span.output == 3
    assert span.status == "ok"
    assert span.latency_ms is not None
    assert span.latency_ms > 0  # Verify latency is tracked (not a specific threshold — timer precision varies by OS)

    clear_current_trace(token)

@pytest.mark.asyncio
async def test_tracing_error_capture():
    trace = TraceData(
        trace_id="test-trace-error",
        timestamp=iso_z(now_utc()),
        update_type="test"
    )
    token = set_current_trace(trace)

    with pytest.raises(ValueError):
        await error_func()
    
    current = get_current_trace()
    assert len(current.spans) == 1
    
    span = current.spans[0]
    assert span.name == "error_func"
    assert span.status == "error"
    assert "Test error in tracing" in span.error

    clear_current_trace(token)

def test_trace_logger_serialization():
    logger = get_trace_logger()
    
    trace = TraceData(
        trace_id="log-test-1",
        timestamp=iso_z(now_utc()),
        update_type="test",
        user_id=123
    )
    
    start = now_utc()
    trace.end(start, start, False, None)
    
    json_str = trace.model_dump_json()
    assert '"trace_id":"log-test-1"' in json_str
    
    # Send it to the queue logger
    logger.log_trace_json(json_str)
    
    # We must explicitly call shutdown to flush the queue during tests
    logger.shutdown()

    # The file "logs/traces.jsonl" should now exist and contain this trace
    import os
    assert os.path.exists("logs/traces.jsonl")
    
    with open("logs/traces.jsonl", "r", encoding="utf-8") as f:
        content = f.read()
        assert "log-test-1" in content
