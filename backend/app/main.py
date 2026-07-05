import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import ALLOWED_ORIGIN
from app.db import AsyncSessionLocal
from app.middleware.auth import require_api_key
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.rate_limit import limiter
from app.models.traces import ApiRequestLog
from app.retrieval.hybrid import load_aliases
from app.routers import admin, chat, disagreements, emails, key_points, meta, summaries, trade_ideas


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as db:
        await load_aliases(db)
    yield


app = FastAPI(title="Macro RAG API", lifespan=lifespan)

# Per-IP rate limiting (B.4) — default ceiling on all routes; chat has its own
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Reject oversized /api/* bodies before they're read (B.4 / hardening 1.2)
app.add_middleware(BodySizeLimitMiddleware)

# Bearer-token gate on /api/* — registered after CORS so CORS wraps it
app.middleware("http")(require_api_key)


@app.middleware("http")
async def log_api_requests(request: Request, call_next):
    """Coarse audit log of every /api/* request except /api/chat (richly traced)."""
    start = time.perf_counter()
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api") and path != "/api/chat":
        duration_ms = int((time.perf_counter() - start) * 1000)
        try:
            async with AsyncSessionLocal() as session:
                session.add(ApiRequestLog(
                    method=request.method,
                    path=path,
                    query_params=dict(request.query_params) or None,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    client_host=request.client.host if request.client else None,
                ))
                await session.commit()
        except Exception as exc:  # logging must never break a request
            print(f"[trace] failed to log api request: {exc}", file=sys.stderr)
    return response


app.include_router(key_points.router,    prefix="/api/key-points")
app.include_router(trade_ideas.router,   prefix="/api/trade-ideas")
app.include_router(disagreements.router, prefix="/api/disagreements")
app.include_router(summaries.router,     prefix="/api")
app.include_router(emails.router,        prefix="/api/emails")
app.include_router(meta.router,          prefix="/api/meta")
app.include_router(chat.router,          prefix="/api")
app.include_router(admin.router,         prefix="/api/admin")

@app.get("/admin")
async def admin_page():
    # StaticFiles(html=True) only maps directories to index.html, not /admin → admin.html.
    return FileResponse("../frontend/admin.html")


# Serve frontend — must come last so /api routes take priority
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
