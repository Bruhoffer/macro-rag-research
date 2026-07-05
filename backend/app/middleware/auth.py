"""Access control for /api/* routes (HOSTING_PLAN.md B.2/B.5).

Two tiers:
  /api/admin/*  — ALWAYS requires ADMIN_API_KEY, in both access modes.
                  Fail-closed: unset key => 503, never silently open.
  other /api/*  — ACCESS_MODE "open":    public (cost is bounded by rate
                                          limits + the daily chat budget cap)
                  ACCESS_MODE "private": requires MACRO_RAG_API_KEY (fail-closed)

Static frontend files stay public — they contain no data; every byte of data
flows through /api/*.
"""

import secrets

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.config import ACCESS_MODE, ADMIN_API_KEY, MACRO_RAG_API_KEY


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    return auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""


def _check(request: Request, expected: str, label: str) -> JSONResponse | None:
    """Return an error response, or None if the request is authorized."""
    if not expected:
        return JSONResponse(
            status_code=503,
            content={"detail": f"Server auth not configured — set {label}"},
        )
    token = _bearer_token(request)
    # constant-time compare — never leak key length/prefix via timing
    if not (token and secrets.compare_digest(token, expected)):
        return JSONResponse(status_code=401, content={"detail": f"Invalid or missing {label}"})
    return None


async def require_api_key(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api"):
        return await call_next(request)

    # CORS preflight carries no Authorization header by design
    if request.method == "OPTIONS":
        return await call_next(request)

    if path.startswith("/api/admin"):
        error = _check(request, ADMIN_API_KEY, "ADMIN_API_KEY")
    elif ACCESS_MODE == "open":
        error = None
    else:
        error = _check(request, MACRO_RAG_API_KEY, "MACRO_RAG_API_KEY")

    return error if error is not None else await call_next(request)
