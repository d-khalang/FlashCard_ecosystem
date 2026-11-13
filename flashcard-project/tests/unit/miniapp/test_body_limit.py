"""
The request size limit: 413 before anything else, by header and while streaming.
"""
import json

import pytest

from flashcard.miniapp.api import MAX_BODY_BYTES, create_app
from flashcard.settings import get_setting


async def _call(app, *, headers, chunks, path="/api/v1/study/grade", method="POST"):
    """Drive the ASGI app directly: returns (status, body, how many chunks were read)."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path,
             "raw_path": path.encode(), "query_string": b"", "root_path": "", "scheme": "http",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
             "client": ("t", 1), "server": ("t", 80)}
    pending = list(chunks)
    read = []
    sent = []

    async def receive():
        if pending:
            chunk = pending.pop(0)
            read.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body, read, sent


@pytest.fixture
def app():
    return create_app(get_setting())


def test_the_limit_is_64_kb():
    assert MAX_BODY_BYTES == 64 * 1024


async def test_a_large_declared_length_is_refused_without_reading_the_body(app):
    status, body, read, _ = await _call(
        app, headers={"content-length": str(MAX_BODY_BYTES + 1), "content-type": "application/json"},
        chunks=[b"x" * 10])

    assert status == 413 and read == []
    assert json.loads(body)["error"]["code"] == "payload_too_large"


async def test_it_is_refused_before_sign_in_on_every_route(app):
    for method, path in (("POST", "/api/v1/cards/preview"), ("PATCH", "/api/v1/settings"),
                         ("POST", "/api/v1/collection/import"), ("GET", "/api/v1/me"), ("POST", "/nowhere")):
        status, *_ = await _call(app, headers={"content-length": "999999"}, chunks=[b""], path=path, method=method)
        assert status == 413, path


async def test_a_body_without_a_length_is_cut_off_while_streaming(app):
    chunk = b"x" * 16384
    chunks = [chunk] * 6  # 96 KB, no Content-Length (chunked)

    status, body, read, _ = await _call(app, headers={"content-type": "application/json"}, chunks=chunks)

    assert status == 413
    assert sum(read) <= MAX_BODY_BYTES + len(chunk)  # stopped reading soon after the limit
    assert len(read) < len(chunks)


async def test_a_length_that_lies_is_cut_off_too(app):
    chunks = [b"x" * 16384] * 6

    status, *_ = await _call(app, headers={"content-length": "10", "content-type": "application/json"}, chunks=chunks)

    assert status == 413


async def test_a_nonsense_length_does_not_get_past_the_streaming_check(app):
    status, *_ = await _call(app, headers={"content-length": "abc"}, chunks=[b"x" * 70000])

    assert status == 413


async def test_a_body_exactly_at_the_limit_is_let_through(app):
    status, body, *_ = await _call(
        app, headers={"content-length": str(MAX_BODY_BYTES), "content-type": "application/json"},
        chunks=[b"x" * MAX_BODY_BYTES])

    assert status == 401 or status == 422  # past the limit check: it is the sign-in or the body that fails


async def test_a_normal_request_is_untouched(app):
    body = json.dumps({"delivery_id": -1}).encode()

    status, *_ = await _call(app, headers={"content-length": str(len(body)), "content-type": "application/json"}, chunks=[body])

    assert status == 401


async def test_the_refusal_carries_the_security_headers(app):
    _, _, _, sent = await _call(app, headers={"content-length": "999999"}, chunks=[b""])

    headers = {k.lower(): v for k, v in sent[0]["headers"]}
    assert b"content-security-policy" in headers and headers[b"x-content-type-options"] == b"nosniff"
