"""Tests for the request body-size cap and ChatRequest message validators (1.2)."""

import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.body_limit import MAX_BODY_BYTES, BodySizeLimitMiddleware
from app.routers.chat import MAX_MESSAGE_CHARS, MAX_MESSAGES, ChatRequest


def _app():
    async def echo(request):
        body = await request.body()
        return PlainTextResponse(f"got {len(body)}")

    app = Starlette(routes=[
        Route("/api/echo", echo, methods=["POST"]),
        Route("/other", echo, methods=["POST"]),
    ])
    app.add_middleware(BodySizeLimitMiddleware)
    return TestClient(app)


class TestBodySizeLimit:
    def test_small_body_passes(self):
        r = _app().post("/api/echo", content=b"x" * 100)
        assert r.status_code == 200

    def test_oversized_body_rejected(self):
        r = _app().post("/api/echo", content=b"x" * (MAX_BODY_BYTES + 1))
        assert r.status_code == 413

    def test_non_api_path_not_limited(self):
        r = _app().post("/other", content=b"x" * (MAX_BODY_BYTES + 1))
        assert r.status_code == 200


class TestChatRequestValidators:
    def test_normal_request_ok(self):
        ChatRequest(messages=[{"role": "user", "content": "hello"}])

    def test_too_many_messages_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[{"role": "user", "content": "x"}] * (MAX_MESSAGES + 1))

    def test_overlong_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[{"role": "user", "content": "x" * (MAX_MESSAGE_CHARS + 1)}])

    def test_missing_content_key_is_safe(self):
        # a message with no content should not crash the validator
        ChatRequest(messages=[{"role": "assistant"}])
