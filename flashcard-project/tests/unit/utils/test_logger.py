"""
Tests for the console encoding fix in the logger.
"""
import io

from flashcard.utils.logger import _use_utf8


def test_cp1252_stream_can_write_the_log_emoji():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")

    _use_utf8(stream)
    stream.write("⚡ INFO")
    stream.flush()

    assert raw.getvalue().decode("utf-8") == "⚡ INFO"


def test_stream_without_reconfigure_is_left_alone():
    stream = io.StringIO()

    _use_utf8(stream)
    stream.write("⚡")

    assert stream.getvalue() == "⚡"
