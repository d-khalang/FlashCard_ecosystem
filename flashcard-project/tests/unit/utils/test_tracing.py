"""
Unit tests for the execution tracing system.

Tests the @observe decorator, TraceData lifecycle,
and TraceLogger serialization.
"""
import asyncio
import os
import pytest
from unittest.mock import MagicMock, patch

from flashcard.schemas.trace import TraceData
from flashcard.utils.tracing import (
    set_current_trace,
    observe,
    get_current_trace,
    clear_current_trace,
    finalize_trace,
)
from flashcard.utils.time import now_utc, iso_z
from flashcard.services.trace_logger import get_trace_logger


# ---------------------------------------------------------------------------
# Decorated test functions
# ---------------------------------------------------------------------------
@observe(name="dummy_func")
async def dummy_func(a: int, b: int) -> int:
    await asyncio.sleep(0.01)
    return a + b


@observe(name="error_func")
async def error_func():
    raise ValueError("Test error in tracing")


@observe(name="nested_outer")
async def nested_outer():
    return await nested_inner()


@observe(name="nested_inner")
async def nested_inner():
    return 42


# ===================================================================
# @observe decorator — success path
# ===================================================================
class TestObserveSuccess:

    async def test_captures_inputs_and_output(self):
        trace = TraceData(trace_id="test-1", timestamp=iso_z(now_utc()), update_type="test")
        token = set_current_trace(trace)

        result = await dummy_func(1, 2)

        assert result == 3
        current = get_current_trace()
        assert len(current.spans) == 1

        span = current.spans[0]
        assert span.name == "dummy_func"
        assert span.inputs == {"a": 1, "b": 2}
        assert span.output == 3
        assert span.status == "ok"

        clear_current_trace(token)

    async def test_tracks_latency(self):
        trace = TraceData(trace_id="test-lat", timestamp=iso_z(now_utc()), update_type="test")
        token = set_current_trace(trace)

        await dummy_func(1, 2)

        span = get_current_trace().spans[0]
        assert span.latency_ms is not None
        assert span.latency_ms > 0

        clear_current_trace(token)

    async def test_nested_observe_captures_both_spans(self):
        trace = TraceData(trace_id="test-nest", timestamp=iso_z(now_utc()), update_type="test")
        token = set_current_trace(trace)

        result = await nested_outer()

        assert result == 42
        current = get_current_trace()
        assert len(current.spans) == 2
        names = {s.name for s in current.spans}
        assert names == {"nested_outer", "nested_inner"}

        clear_current_trace(token)


# ===================================================================
# @observe decorator — error path
# ===================================================================
class TestObserveError:

    async def test_captures_error_details(self):
        trace = TraceData(trace_id="test-err", timestamp=iso_z(now_utc()), update_type="test")
        token = set_current_trace(trace)

        with pytest.raises(ValueError):
            await error_func()

        span = get_current_trace().spans[0]
        assert span.name == "error_func"
        assert span.status == "error"
        assert "Test error in tracing" in span.error

        clear_current_trace(token)


# ===================================================================
# @observe without active trace — should not crash
# ===================================================================
class TestObserveNoTrace:

    async def test_works_without_active_trace(self):
        """If no trace is set, @observe should still run the function."""
        result = await dummy_func(5, 10)
        assert result == 15


# ===================================================================
# TraceLogger serialization
# ===================================================================
class TestTraceLogger:

    def test_trace_serializes_to_json(self):
        trace = TraceData(
            trace_id="json-test",
            timestamp=iso_z(now_utc()),
            update_type="test",
            user_id=123,
        )
        start = now_utc()
        trace.end(start, start, False, None)

        json_str = trace.model_dump_json()
        assert '"trace_id":"json-test"' in json_str

    def test_logger_writes_to_file(self, tmp_path):
        """Trace logger should write JSONL to the target file."""
        trace_file = tmp_path / "traces.jsonl"

        # Create a fresh logger pointing at tmp_path
        from flashcard.services.trace_logger import TraceLogger
        logger = TraceLogger(log_dir=str(tmp_path))

        trace = TraceData(
            trace_id="file-test",
            timestamp=iso_z(now_utc()),
            update_type="test",
        )
        start = now_utc()
        trace.end(start, start, False, None)

        logger.log_trace_json(trace.model_dump_json())
        logger.shutdown()

        assert trace_file.exists()
        assert "file-test" in trace_file.read_text(encoding="utf-8")


class TestFinalizeTrace:

    def test_finalize_trace_sets_error_and_clears_context(self):
        trace = TraceData(
            trace_id="finalize-test",
            timestamp=iso_z(now_utc()),
            update_type="test",
        )
        token = set_current_trace(trace)
        mock_logger = MagicMock()
        start = now_utc()

        with patch("flashcard.services.trace_logger.get_trace_logger", return_value=mock_logger):
            finalize_trace(trace, token, start, has_error=True, error_msg="boom")

        assert trace.status == "error"
        assert trace.error == "boom"
        assert trace.total_latency_ms is not None
        assert get_current_trace() is None
        mock_logger.log_trace_json.assert_called_once()
