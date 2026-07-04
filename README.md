# Macro RAG

A local-first analytics and chat system for sell-side macro research emails. Ingests research email exports into PostgreSQL, extracts key points and trade ideas, and serves them through a browse UI and a Claude-powered chat assistant with hybrid retrieval (pgvector HNSW + BM25 full-text, fused via Reciprocal Rank Fusion).

**This repo ships no data.** You bring your own email exports (`.eml` files + parsed CSVs); the paths are configured via environment variables.

## Stack

- **Backend**: FastAPI (Python 3.12), SQLAlchemy 2 async, Alembic
- **Database**: PostgreSQL 16 + pgvector (Docker)
- **Retrieval**: OpenAI `text-embedding-3-small` (1536-dim) + Postgres tsvector, RRF fusion
- **Chat**: Claude with tool use + SSE streaming
- **Frontend**: static HTML + Alpine.js + Tailwind (no build step), served by FastAPI

## Prerequisites

- Docker (for Postgres)
- Python 3.12+
- An Anthropic API key (chat) and an OpenAI API key (embeddings)

## Setup

```bash
# 1. Start Postgres (exposed on host port 5433)
docker compose up -d

# 2. Install the backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. Configure environment
cp ../.env.example ../.env
# then edit ../.env: add your API keys and data paths

# 4. Create the schema
alembic upgrade head

# 5. Load your data (reads CSVs from RAW_DATA_DIR)
python scripts/migrate.py

# 6. Generate embeddings + build HNSW/FTS indexes
python scripts/embed.py

# 7. Run the app
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 for the main UI, http://localhost:8000/admin for the observability dashboard.

## Environment variables

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Postgres password (docker compose interpolates it; default `macrorag`) |
| `DATABASE_URL` | Async connection string (`postgresql+asyncpg://...@localhost:5433/macrorag`) |
| `DATABASE_URL_SYNC` | Sync connection string (Alembic + scripts) |
| `ANTHROPIC_API_KEY` | Claude chat |
| `OPENAI_API_KEY` | Embeddings |
| `RAW_DATA_DIR` | Path to parsed CSV exports (relative to `backend/`) |
| `RAW_EMAILS_DIR` | Path to raw `.eml` files (relative to `backend/`) |

## Development

```bash
# Tests
pytest tests/

# Lint & format
ruff check app/ && ruff format app/
```

## License

MIT — see [LICENSE](LICENSE).
