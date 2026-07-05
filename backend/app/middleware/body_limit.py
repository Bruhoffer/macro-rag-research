"""Request body size cap for /api/* (HOSTING.md 1.2).

Pure-ASGI middleware. Rejects any /api/* request whose declared Content-Length
exceeds the cap with 413, before the body is read or the route runs — cheap
protection against oversized-payload memory/bandwidth DoS. 64 KB comfortably
fits a long multi-turn chat history.

Content-Length covers every well-behaved and scripted client (httpx, requests,
curl all set it). The per-message caps on ChatRequest bound the parsed size as
a second layer for anything that slips through.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

MAX_BODY_BYTES = 64 * 1024


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api"):
            await self.app(scope, receive, send)
            return

        content_length = dict(scope.get("headers") or []).get(b"content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            await self._reject(send)
            return

        await self.app(scope, receive, send)

    async def _reject(self, send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"detail":"Request body too large"}',
        })
