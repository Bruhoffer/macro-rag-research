from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import AsyncSessionLocal
from app.retrieval.hybrid import load_aliases
from app.routers import chat, disagreements, emails, key_points, meta, summaries, trade_ideas


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as db:
        await load_aliases(db)
    yield


app = FastAPI(title="Macro RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(key_points.router,    prefix="/api/key-points")
app.include_router(trade_ideas.router,   prefix="/api/trade-ideas")
app.include_router(disagreements.router, prefix="/api/disagreements")
app.include_router(summaries.router,     prefix="/api")
app.include_router(emails.router,        prefix="/api/emails")
app.include_router(meta.router,          prefix="/api/meta")
app.include_router(chat.router,          prefix="/api")

# Serve frontend — must come last so /api routes take priority
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
