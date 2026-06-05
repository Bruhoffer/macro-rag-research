# CLAUDE.md — macro-rag

Project-specific rules for Claude Code when working in `email-ai/macro-rag/`.

## Project Context

Macro RAG — a local-first analytics + chat system built on top of a macro hedge fund' macro research email exports. Full plan is in `PLAN.md`.

**DO NOT touch** `email-ai/email-ai/` (old Databricks codebase) or any file outside `email-ai/macro-rag/`.

## Commands

All commands run from `backend/`:
```bash
source .venv/bin/activate

# Apply DB migrations
alembic upgrade head

# Run data migration from CSVs → Postgres
python scripts/migrate.py

# Run embeddings
python scripts/embed.py

# Start API server
uvicorn app.main:app --reload --port 8000
```

**Docker (Postgres):** `docker compose up -d` from `macro-rag/` root.  
Container `macro_rag_db` runs on **port 5433** (5432 is taken by local Postgres).  
Connect string: `postgresql://macrorag:macrorag@localhost:5433/macrorag`

## Git Commit Rule

**Commit at every meaningful milestone — not just at phase end.**

A milestone is: a file is written and runs, a migration is applied, a script produces verified output, a bug is fixed, a phase task is checked off.

Commit message format:
```
<type>: <short description of what changed and why>
```
Types: `feat`, `fix`, `chore`, `refactor`, `docs`

Examples:
```
feat: add alembic migration 001 — creates all 12 tables + indexes
feat: implement migrate.py with per-table stats reporting
fix: change Docker host port to 5433 to avoid conflict with local Postgres
feat: populate tsvector columns and build HNSW indexes after embedding
```

After every commit, update the relevant `[ ]` task in `PLAN.md` to `[x]`.

## Key Gotchas

1. `emails_parsed.csv` rows: ~5,983 (not 637k — original estimate was wrong). After `load_end_dt IS NULL + status='ok'` + dedup → ~5,822 unique emails.
2. `key_points_enrichments` joins on `keypoint_id` column (NOT `key_point_id`) — note the missing underscore.
3. `source_org = 'Others'` → use `suggested_source_org` as the real bank name. Column `effective_source_org` stores the resolved value.
4. Docker exposed on **5433**, not 5432. `.env` and all connection strings must use 5433.
5. `label_map` keys in topic_summaries are `"1"`, `"2"` etc. (plain integers as strings), not `"[1]"`.
6. `key_point_citation` is always a verbatim substring of `email_body` — use `indexOf` for highlighting, no fuzzy matching needed.
7. HNSW indexes must be built **after** embeddings are populated — don't add them in Phase 1 migration.

## Architecture Quick Reference

- **Port 5433**: Postgres (Docker)
- **Port 8000**: FastAPI backend
- **Frontend**: static files served by FastAPI from `frontend/` at `GET /`
- **Two retrieval paths**: key-point hybrid (Path 1) + email-chunk parent-child (Path 2)
- **Embedding model**: `text-embedding-3-small` (OpenAI, 1536-dim)
- **Chat model**: `claude-sonnet-4-6` with tool use + SSE streaming
