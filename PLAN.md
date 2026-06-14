# Macro RAG — Full Project Plan

**Last updated:** 2026-06-05  
**Status:** Phase 2 COMPLETE — all embeddings populated, tsvectors built, HNSW indexes live. Phase 3 in progress.  
**Project folder:** `email-ai/macro-rag/` (own git repo)  
**Reference data:** `email-ai/raw-data/*.csv` (Delta Lake exports, read-only)  
**Reference emails:** `email-ai/raw-emails/MM/DD/*.eml` (read-only)  
**Old codebase:** `email-ai/email-ai/` — DO NOT TOUCH

---

## What We Are Building

A local-first (later team-deployed) analytics and RAG system on top of the existing Macro Email AI data exports.

**Two interfaces:**
1. **Data browser** — filterable feed of key points, trade ideas, disagreements, daily summaries, webinars
2. **Chat interface** — streaming Claude tool-use chat that answers analytical questions about macro data

**Inspired by:** Anthropic's self-service analytics best practices (three failure modes: entity ambiguity, data staleness, retrieval failure).

### Scale
| Artifact type | Count |
|---|---|
| Key points (extracted + enriched) | ~40,784 |
| Trade ideas (extracted + enriched) | ~4,885 |
| Emails (unique, deduplicated) | ~5,822 |
| Email chunks (parent-child retrieval) | ~73,767 |
| Topic summaries | ~1,702 |
| Trade summaries | ~508 |
| Disagreements | ~3,010 |
| Disagreement validations | ~8,043 |
| Webinars | ~2,102 |
| **Total indexed artifacts** | **~140,623** |

### Resume-level capabilities
- **Dual-path hybrid RAG** — structured key-point retrieval (Path 1) + email-chunk parent-child retrieval (Path 2)
- **Low-latency hybrid search** — HNSW dense vector indexing (pgvector) + BM25 full-text search (PostgreSQL tsvector), fused via Reciprocal Rank Fusion (k=60)
- **Autonomous LLM tool-routing** — Claude's tool-use API autonomously selects which retrieval path(s) to invoke and whether to run SQL aggregations or semantic search, based on query intent alone — no explicit user routing required
- **Intraday macro-economic analysis** — designed for analysts doing morning reads of sell-side research; surfaces cross-bank sentiment disagreements, trade ideas, and topic summaries with clickable citation provenance

---

## Folder Structure (Target)

```
macro-rag/
├── PLAN.md                    ← this file
├── .gitignore
├── docker-compose.yml         ← Postgres + pgvector + backend
├── .env.example
│
├── backend/                   ← FastAPI Python app
│   ├── pyproject.toml
│   ├── alembic/               ← migrations
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py              ← SQLAlchemy async engine
│   │   ├── models/            ← ORM models
│   │   ├── routers/           ← API routes
│   │   ├── retrieval/         ← hybrid search logic
│   │   ├── chat/              ← Claude tool-use chat
│   │   └── ingest/            ← migration + embedding scripts
│   └── scripts/
│       ├── migrate.py         ← load CSV → Postgres
│       └── embed.py           ← generate embeddings
│
└── frontend/                  ← Vanilla JS + Tailwind + Alpine.js
    ├── index.html
    ├── css/
    ├── js/
    └── assets/
```

---

## Tech Stack

| Layer | Tool | Notes |
|---|---|---|
| Database | PostgreSQL 16 + pgvector | Docker locally; Supabase for team deploy |
| Backend | Python 3.12 + FastAPI + SQLAlchemy (async) | Same language as old codebase |
| LLM (chat) | Anthropic Claude — claude-sonnet-4-6 | Tool use for structured retrieval |
| Embeddings | OpenAI text-embedding-3-small (1536-dim) | ~56k key points + ~50k email chunks ≈ $0.03 |
| Full-text search | PostgreSQL tsvector + GIN index | BM25-equivalent, no extra infra |
| Frontend | HTML + Tailwind CDN + Alpine.js | No build step |
| Dev browser testing | Playwright MCP (npx @playwright/mcp@latest) | See setup section |
| Local orchestration | Docker Compose | One command startup |

---

## Data Available (read-only exports)

| File | Rows (approx) | Key columns |
|---|---|---|
| `key_points.csv` | ~48k | key_point_id, email_content_hash, email_sent_dt, source_org, key_point_text, key_point_citation, key_point_context |
| `key_points_enrichments.csv` | ~43k | keypoint_id, topics[], geographies[], sentiment, time_reference, future_time_horizon |
| `trade_ideas.csv` | ~7.5k | trade_idea_id, email_content_hash, email_sent_dt, source_org, trade_idea_text, trade_idea_citation, trade_idea_context |
| `trade_ideas_enrichments.csv` | ~7.5k | trade_idea_id, asset_class, time_horizon, geographies[], legs (JSON), target_price, stop_price, trigger_condition |
| `emails_parsed.csv` | ~5,983 rows → ~5,822 unique after SCD-2 filter + dedup | email_content_hash, file_name, email_subject, email_from, email_sent_dt, email_body, email_body_length |
| `topic_summaries.csv` | ~10.5k | topic, window_start, window_end, bullets[], source_orgs[], kp_count, label_map (JSON: [N]→key_point_id) |
| `trade_summaries.csv` | ~? | group_key (asset_class), window_start, window_end, bullets[], label_map |
| `disagreements.csv` | ~3k | disagreement_id, group_key (topic), geography, window_start, window_end, scale, n_banks, bank_positions (JSON) |
| `disagreement_validations.csv` | ~8.7k | validation_id, disagreement_id, status, is_false_positive, resolution_summary, agent_confidence, bank_analysis (JSON) |
| `webinars.csv` | ~? | file_name, source_bank, is_webinar, title, host_bank, event_datetime, topic_summary, speakers (JSON), url |
| `source_orgs_approved.csv` | ~30 | org_shortform_name (GS, JPM...), org_name, org_aliases[] |
| `topics_approved.csv` | ~20 | topic_name, description (full text for LLM) |
| `geographies_approved.csv` | ~30 | geography_name (US, EM, CHN...), description |

**Email files:** `raw-emails/MM/DD/{file_name}.eml` — accessible locally, no S3 needed.

---

## Database Schema

### Why no SCD-2
The old codebase used SCD-2 (load_end_dt IS NULL = current row) for versioning across pipeline runs. We don't need this — we keep only the current/latest version of each record by filtering `load_end_dt IS NULL` during migration.

### Core tables

```sql
-- Deduplicated emails (PK: email_content_hash — content-derived, stable)
emails (
    email_content_hash  TEXT PRIMARY KEY,
    file_name           TEXT,           -- "FW_ GS MORNING.eml"
    email_subject       TEXT,           -- "GS MORNING"
    email_from          TEXT,           -- "Jane Doe <sender@fund.com>"
    email_sent_dt       TIMESTAMPTZ,
    email_body          TEXT,           -- full plain-text body (for viewer)
    email_body_length   INT
)

-- Key points: deduplicated, enrichments joined in
key_points_full (
    key_point_id         UUID PRIMARY KEY,
    email_content_hash   TEXT REFERENCES emails,
    email_sent_dt        TIMESTAMPTZ,
    email_subject        TEXT,          -- denormalised from emails for display
    file_name            TEXT,          -- denormalised for local .eml path reconstruction
    source_org           TEXT,          -- "GS", "JPM", "Others"
    suggested_source_org TEXT,          -- actual name when source_org = "Others"
    effective_source_org TEXT,          -- COALESCE(source_org != 'Others', suggested_source_org)
    key_point_text       TEXT,
    key_point_citation   TEXT,          -- verbatim quote — used for highlighting in email viewer
    key_point_context    TEXT,          -- surrounding sentences
    topics               TEXT[],        -- ['Inflation', 'Labor Market']
    suggested_topics     TEXT[],
    geographies          TEXT[],        -- ['US', 'CHN', 'EM']
    suggested_geographies TEXT[],
    sentiment            TEXT,          -- 'very bearish' | 'bearish' | 'neutral' | 'bullish' | 'very bullish'
    sentiment_score      SMALLINT,      -- -2 | -1 | 0 | 1 | 2  (for range queries)
    time_reference       TEXT,          -- 'past' | 'present' | 'future'
    future_time_horizon  TEXT,          -- 'Near-term (0-3m)' | 'Medium-term (3-12m)' | 'Long-term (1y+)'
    kp_embedding         VECTOR(1536),  -- text-embedding-3-small on (text + citation + context)
    kp_fts               TSVECTOR       -- generated, for BM25
)

-- Trade ideas: enrichments joined in
trade_ideas_full (
    trade_idea_id        UUID PRIMARY KEY,
    email_content_hash   TEXT REFERENCES emails,
    email_sent_dt        TIMESTAMPTZ,
    email_subject        TEXT,
    file_name            TEXT,
    source_org           TEXT,
    suggested_source_org TEXT,
    effective_source_org TEXT,
    trade_idea_text      TEXT,
    trade_idea_citation  TEXT,
    trade_idea_context   TEXT,
    asset_class          TEXT,          -- 'Rates' | 'FX' | 'Equities' | 'Credit' | ...
    suggested_asset_class TEXT,
    time_horizon         TEXT,          -- 'Near-term (0-3m)' | ...
    geographies          TEXT[],
    target_price         TEXT,
    stop_price           TEXT,
    trigger_condition    TEXT,
    legs                 JSONB,         -- [{instrument, direction, action}]
    ti_embedding         VECTOR(1536),
    ti_fts               TSVECTOR
)

-- Email chunks: parent-child retrieval path
email_chunks (
    chunk_id             UUID PRIMARY KEY,
    email_content_hash   TEXT REFERENCES emails,
    chunk_index          INT,           -- 0-based position in email
    chunk_text           TEXT,          -- ~200-350 token window
    chunk_embedding      VECTOR(1536),
    -- denormalised for pre-filtering
    email_sent_dt        TIMESTAMPTZ,
    email_subject        TEXT,
    source_org           TEXT           -- inferred from key_points for same email_content_hash
)

-- Disagreements (confirmed non-false-positive)
disagreements (
    disagreement_id      UUID PRIMARY KEY,
    group_key            TEXT,          -- topic name
    geography            TEXT,
    window_start         TIMESTAMPTZ,
    window_end           TIMESTAMPTZ,
    scale                TEXT,          -- 'High' | 'Medium' | 'Low'
    n_banks              INT,
    sentiment_spread     INT,
    bank_positions       JSONB          -- [{source_org, sentiment, geographies[]}]
)

-- Disagreement validations (one per validated disagreement, canonical only)
disagreement_validations (
    validation_id        UUID PRIMARY KEY,
    disagreement_id      UUID REFERENCES disagreements,
    group_key            TEXT,
    geography            TEXT,
    window_start         TIMESTAMPTZ,
    window_end           TIMESTAMPTZ,
    status               TEXT,          -- 'resolved' | 'inconclusive' | 'dismissed' | 'false_positive'
    is_false_positive    BOOLEAN,
    false_positive_reason TEXT,
    resolution_summary   TEXT,
    agent_confidence     FLOAT,
    bank_analysis        JSONB          -- [{source_org, subject_entity, bull_bear, position_summary, value_claim}]
)

-- Topic summaries (pre-computed daily bullets with citation map)
topic_summaries (
    id                   UUID PRIMARY KEY,
    topic                TEXT,
    window_start         TIMESTAMPTZ,
    window_end           TIMESTAMPTZ,
    bullets              JSONB,         -- array of bullet strings with [N] footnote labels
    bullet_count         INT,
    source_orgs          TEXT[],
    kp_count             INT,
    label_map            JSONB          -- {"[25]": "key_point_uuid", ...} — clickable footnotes
)

-- Trade summaries
trade_summaries (
    id                   UUID PRIMARY KEY,
    group_key            TEXT,          -- asset_class name
    window_start         TIMESTAMPTZ,
    window_end           TIMESTAMPTZ,
    bullets              JSONB,
    bullet_count         INT,
    source_orgs          TEXT[],
    kp_count             INT,
    label_map            JSONB          -- {"[N]": "trade_idea_uuid", ...}
)

-- Webinars
webinars (
    webinar_id           UUID PRIMARY KEY,
    file_name            TEXT,
    source_bank          TEXT,
    is_webinar           BOOLEAN,
    title                TEXT,
    host_bank            TEXT,
    event_datetime       TEXT,          -- as extracted (may be fuzzy)
    event_timezone       TEXT,
    topic_summary        TEXT,
    speakers             JSONB,         -- [{name, title}]
    url                  TEXT,
    location             TEXT,
    created_datetime     TIMESTAMPTZ
)

-- Reference tables
source_orgs (org_shortform_name PK, org_name, org_aliases TEXT[])
topics (topic_name PK, description TEXT, is_active BOOLEAN)
geographies (geography_name PK, description TEXT, is_active BOOLEAN)
```

### Indexes

```sql
-- Key points
CREATE INDEX ON key_points_full USING hnsw (kp_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX ON key_points_full USING GIN (topics);
CREATE INDEX ON key_points_full USING GIN (geographies);
CREATE INDEX ON key_points_full USING GIN (kp_fts);
CREATE INDEX ON key_points_full (source_org, email_sent_dt DESC);
CREATE INDEX ON key_points_full (sentiment_score, email_sent_dt DESC);
CREATE INDEX ON key_points_full (time_reference);
CREATE INDEX ON key_points_full (email_sent_dt DESC);

-- Trade ideas
CREATE INDEX ON trade_ideas_full USING hnsw (ti_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX ON trade_ideas_full USING GIN (geographies);
CREATE INDEX ON trade_ideas_full USING GIN (ti_fts);
CREATE INDEX ON trade_ideas_full (source_org, email_sent_dt DESC);
CREATE INDEX ON trade_ideas_full (asset_class, email_sent_dt DESC);

-- Email chunks
CREATE INDEX ON email_chunks USING hnsw (chunk_embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX ON email_chunks (email_sent_dt DESC);
CREATE INDEX ON email_chunks (source_org);
```

---

## Retrieval Architecture (Two Complementary Paths)

### Path 1 — Key Point Retrieval (structured intelligence)

**Best for:** "bearish views on EM FX from JPM", "what does Barclays say about credit markets?", disagreement queries

**Embedding:** `key_point_text + " Evidence: " + key_point_citation + " Context: " + key_point_context`  
(Verbatim citation adds domain jargon; context adds surrounding reasoning)

**Four-layer hybrid:**
```
1. Intent classify (lightweight, in-prompt)
       → search_type: semantic | keyword | structured | hybrid
       → extract filters: source_orgs, topics, geographies, sentiments, date_range, time_reference

2. Structured pre-filter (SQL WHERE)
       source_org = ANY(:orgs)
       AND topics && :topics          -- GIN array overlap
       AND geographies && :geos
       AND sentiment_score BETWEEN :min AND :max
       AND email_sent_dt BETWEEN :from AND :to
       AND time_reference = :ref

3. Dual retrieval on filtered candidates
       A. pgvector ANN cosine similarity  →  ranked list A
       B. tsvector BM25 (ts_rank)         →  ranked list B

4. Reciprocal Rank Fusion (k=60)
       score(d) = 0.6 / (60 + rank_A) + 0.4 / (60 + rank_B)
       → top 20 results
```

**Query expansion:** "Goldman" → "GS", "China" → ["CHN", "EM"] using `source_orgs` and `geographies` reference tables before filtering.

### Path 2 — Email Chunk Retrieval (broad coverage)

**Best for:** "find the email about Ueda's speech", "did anyone write about JOLTS this week?", content not captured by key-point extraction

**Chunking strategy:**
- Split email body on double newlines (paragraph boundaries)
- Merge paragraphs < 100 tokens with adjacent paragraph
- Split paragraphs > 400 tokens at sentence boundaries
- Target: 200–350 tokens per chunk
- Each chunk stores: email_content_hash, chunk_index, chunk_text, embedding

**Embedding:** raw `chunk_text` (no metadata mixed in)

**Retrieval:** pgvector ANN on chunk embedding → return parent email (`email_body`, metadata) + the matching chunk highlighted

**Return format:** parent email with matching chunk highlighted (like the citation highlight, but for any content)

### Path Router

```
User query
    │
    ├─► Structured analytical → Path 1 (key points / trade ideas)
    │   e.g. "which banks disagree on rates?", "bearish views on China"
    │
    ├─► Email search / broad → Path 2 (email chunks)  
    │   e.g. "find emails about Ueda", "what did they write about JOLTS"
    │
    └─► Comprehensive → Both paths, merge results, deduplicate by email_content_hash
```

The Claude chat system selects paths via tool descriptions — no explicit classifier needed, Claude infers from question intent.

---

## Chat System (Claude Tool Use)

**Model:** `claude-sonnet-4-6`  
**Mode:** Streaming with tool use  
**System prompt:** Describes the data model, what each tool does, approved entity lists (banks, topics, geographies), and analytical gotchas

### Autonomous tool-routing

Claude receives all 6 tool definitions and autonomously decides:
- **Which tools to call** (zero, one, or multiple) based on question intent
- **Which retrieval path** to invoke — semantic search vs SQL aggregation
- **Whether to chain tools** — e.g. `get_stats` first for a distribution, then `search_key_points` to pull supporting evidence

The analyst types a free-form question; no routing UI or mode-switching is needed.

### Tools

| Tool | Retrieval path | Description |
|---|---|---|
| `search_key_points` | Path 1 — hybrid semantic + BM25 | Query key points by meaning + filters (bank, topic, geography, sentiment, date, time_reference) |
| `search_trade_ideas` | Path 1 — hybrid semantic + BM25 | Query trade ideas by meaning + filters (bank, asset_class, geography, horizon, date) |
| `search_emails` | Path 2 — chunk ANN → parent email + related insights join | Broad email search; returns matching chunk + full parent email with chunk highlighted + all key points / trade ideas extracted from that same email (joined via `email_content_hash`) |
| `get_disagreements` | SQL structured query | Fetch validated cross-bank disagreements, filtered by topic, geography, scale, date |
| `get_topic_summary` | SQL exact match | Retrieve pre-computed daily bullet summaries with clickable `[N]` footnotes → key_point_id |
| `get_stats` | SQL aggregation | Run COUNT/GROUP BY analytics: count_by_bank, sentiment_distribution, topic_frequency, asset_class_breakdown — returns structured numbers Claude can narrate |

### What `get_stats` can answer (SQL aggregations)
- "Which banks published the most bearish views on US rates this month?"
- "What is the sentiment breakdown across topics for Goldman Sachs?"
- "How many trade ideas per asset class were published in Q2?"
- "Which topics saw the most cross-bank disagreements?"

### Provenance footer (every response)
```
Source: [tool names used] · Results: [N] items · Date range: [from] → [to] · Banks: [list]
```

---

## Email Viewer (No S3 Required)

**Link chain:**  
`key_points.email_content_hash` → `emails.email_content_hash` → `emails.email_body`

**For local .eml file access:**  
Reconstruct path from `email_sent_dt` + `file_name`:  
`raw-emails/{MM}/{DD}/{file_name}` (relative to `email-ai/` workspace)

**Citation highlighting:**  
`key_point_citation` is verbatim from the email body → simple JS `indexOf()` to find + highlight in yellow. Works for both key points and email chunks.

**Cross-table join via `email_content_hash`:**  
All four tables share this key — enabling bidirectional enrichment:
- Path 1 result (key point) → open email viewer → shows parent email with citation highlighted
- Path 2 result (chunk) → open email viewer → shows parent email **+ all key points and trade ideas extracted from that email** as a "Related Insights" sidebar

```
email_chunks.email_content_hash
key_points_full.email_content_hash    ─── all share the same hash
trade_ideas_full.email_content_hash       for emails from the same source
emails.email_content_hash (PK)
```

The `search_emails` tool response includes a `related_insights` field populated by:
```sql
SELECT key_point_text, effective_source_org, sentiment, topics, key_point_id
FROM key_points_full
WHERE email_content_hash = ANY(:matched_hashes)
ORDER BY email_content_hash, email_sent_dt
```

**UI flow on click:**
1. Slide-in right panel shows:
   - Matched chunk or key point text (top)
   - Email metadata: Subject, From, Date
   - Full email body with citation/chunk highlighted and scrolled into view
   - **"Related Insights" section** — structured key points and trade ideas extracted from this same email, each clickable to jump to that citation
   - Action buttons: "Download .eml" (streams raw file from backend) | "Copy citation"

**Backend endpoint:**
- `GET /api/emails/{hash}` → JSON with email_body, subject, from, date, file_name, related_key_points[], related_trade_ideas[]
- `GET /api/emails/{hash}/raw` → streams raw `.eml` file from `../raw-emails/MM/DD/{file_name}`

---

## API Design

```
GET  /api/key-points              ?source_org=&topic=&geo=&sentiment=&from=&to=&q=&page=&limit=
GET  /api/key-points/{id}         full record + email metadata
GET  /api/trade-ideas             ?source_org=&asset_class=&geo=&horizon=&from=&to=&q=
GET  /api/trade-ideas/{id}
GET  /api/disagreements           ?topic=&geo=&scale=&from=&to=&confirmed_only=true
GET  /api/disagreements/{id}      with bank_analysis expanded
GET  /api/topic-summaries         ?topic=&date=
GET  /api/trade-summaries         ?asset_class=&date=
GET  /api/webinars                ?from=&to=&host_bank=
GET  /api/emails/{hash}           email body + metadata + related_key_points[] + related_trade_ideas[] (joined via email_content_hash)
GET  /api/emails/{hash}/raw       stream raw .eml file
GET  /api/search                  ?q=&mode=key_points|emails|both
POST /api/chat                    body: {messages, stream: true} → SSE stream
GET  /api/meta/topics             list of approved topics
GET  /api/meta/geographies        list of approved geographies
GET  /api/meta/source-orgs        list of approved source orgs
```

---

## Frontend Design

### Layout
```
┌─────────────────────────────────────────────────────┐
│  🔍 Search bar                     [Chat] [Browse]   │
├──────────────┬──────────────────────────────────────┤
│              │                                       │
│  FILTERS     │   MAIN CONTENT AREA                   │
│  ─────────   │                                       │
│  Date range  │   [Key Points] [Trade Ideas]          │
│  Banks       │   [Disagreements] [Summaries]         │
│  Topics      │   [Webinars]                          │
│  Geography   │                                       │
│  Sentiment   │   Content cards (paginated, 20/page)  │
│  Time ref    │                                       │
│              │                                       │
│              │                                       │
└──────────────┴──────────────────────────────────────┘
```

### Chat mode (replaces main content area)
```
┌──────────────┬──────────────────────────────────────┐
│  FILTERS     │  💬 Chat with macro data              │
│  (collapsed  │  ─────────────────────────────────── │
│   in chat    │  [message bubbles, streaming]         │
│   mode)      │                                       │
│              │  📎 Source cards (expandable)          │
│              │  → click to open email viewer         │
│              │                                       │
│              │  ─────────────────────────────────── │
│              │  [Input box]            [Send ▶]      │
└──────────────┴──────────────────────────────────────┘
```

### Email viewer (right-side slide panel)
```
                              ┌──────────────────────┐
                              │  ✕                   │
                              │  GS MORNING          │
                              │  From: daniel.dooling │
                              │  Date: 2 Jun 2026     │
                              │  Topics: [FX] [Rates] │
                              │  ─────────────────── │
                              │  Key point:           │
                              │  "GS reports that..."│
                              │                       │
                              │  ─────────────────── │
                              │  Email body:          │
                              │  ... text ...         │
                              │  ████ CITATION ████  │ ← highlighted yellow
                              │  ... continues ...    │
                              │                       │
                              │  [📥 Download .eml]   │
                              └──────────────────────┘
```

### Tech
- **Tailwind CSS** (CDN, no build step)
- **Alpine.js** (CDN, reactive state management, ~15KB)
- **Fetch API** for REST calls
- **EventSource** for SSE streaming in chat
- No bundler, no framework, no build step — everything in static files served by FastAPI

---

## Playwright MCP Setup (for frontend development)

Lets Claude Code drive a real browser to verify UI during development — screenshots, click interactions, assertion checks.

### Installation

```bash
# In your terminal (one-time)
npm install -g @playwright/mcp
npx playwright install chromium
```

### Claude Code settings

Add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--headless"]
    }
  }
}
```

Restart Claude Code. I can then use browser tools to:
- Navigate to `http://localhost:8000`
- Click buttons, fill inputs, check that filters work
- Take screenshots of any state
- Verify streaming chat works
- Check that email viewer opens correctly

You don't need to manually verify the UI — I'll check it during development.

---

## Build Phases

### ✅ Phase 0 — Planning (COMPLETE)
- [x] Understand full old codebase + CSV exports
- [x] Design retrieval architecture (two-path hybrid: key points + email chunks)
- [x] Design database schema (all tables with indexes)
- [x] Create `macro-rag` git repo (inside `email-ai/`, own git history)
- [x] Write this plan

---

### ✅ Phase 1 — Postgres + Data Migration (COMPLETE)
**Branch:** `phase/1-migration`  
**Goal:** All data loaded into local Postgres, queryable  
**Note:** Docker exposed on **port 5433** (not 5432) — local Homebrew/Postgres.app was already bound to 5432.

**Tasks:**
- [x] Project folder structure created (`backend/`, `frontend/`, subdirs)
- [x] `docker-compose.yml` — Postgres 16 + pgvector image (`pgvector/pgvector:pg16`)
- [x] `.env` + `.env.example` — DATABASE_URL (port 5433), API keys, data paths
- [x] `backend/pyproject.toml` — all dependencies declared
- [x] `backend/.venv/` — virtual environment created and all packages installed
- [x] Docker Desktop opened → `docker compose up -d` → container `macro_rag_db` healthy on port 5433
- [x] Alembic init + `alembic.ini` config + `alembic/env.py`
- [x] `backend/app/models/` — all 12 ORM models (emails, key_points_full, trade_ideas_full, email_chunks, disagreements, disagreement_validations, topic_summaries, trade_summaries, webinars, source_orgs, topics, geographies)
- [x] `backend/alembic/versions/001_initial_schema.py` — CREATE EXTENSION vector + all tables + all indexes (GIN, btree)
- [x] `alembic upgrade head` — all 12 tables created in DB, confirmed via `\dt`
- [x] `backend/scripts/migrate.py` — reads all CSVs, deduplicates, joins enrichments, writes to Postgres with full stats reporting per table (csv_read → filtered → skipped → attempted → inserted → conflicts)
- [x] **Run `python scripts/migrate.py`** — verified stats output, all counts correct
- [x] Verify: zero conflicts, all email_content_hash FKs satisfied

**Actual CSV sizes (after inspection):**
| CSV | Raw rows | After filter | Notes |
|---|---|---|---|
| emails_parsed | 5,983 | ~5,822 | filter `load_end_dt IS NULL + status='ok'` + dedup by hash |
| key_points | 42,181 | ~40,784 | same filter |
| key_points_enrichments | 41,957 | ~40,119 | join key on `keypoint_id` (note: not `key_point_id`) |
| trade_ideas | 5,256 | ~4,885 | same filter |
| trade_ideas_enrichments | 5,048 | ~4,856 | |
| disagreements | 3,010 | 3,010 | all current, no status col |
| disagreement_validations | 8,045 | ~8,043 | exclude status='failed' only |
| topic_summaries | — | ~1,702 | |
| trade_summaries | — | ~508 | |
| webinars | 7,455 | ~2,102 | |

---

### ✅ Phase 2 — Embeddings (COMPLETE)
**Branch:** `phase/2-embeddings`  
**Goal:** All vectors populated, both retrieval paths ready  
**Note:** Email chunking is already done inside `migrate.py` — chunks written to `email_chunks` table during Phase 1 migration. Phase 2 is just adding vectors to existing rows.

**Tasks:**
- [x] `backend/scripts/embed.py` — embeddings for all three tables with contextual retrieval for email_chunks
  - **key_points_full**: `key_point_text + " Evidence: " + citation + " Context: " + context` — 40,754 rows
  - **trade_ideas_full**: same pattern — 4,885 rows
  - **email_chunks**: Contextual Retrieval — prepend `"Email from {source_org} ({date}, subject: '{subject}'):\n\n{chunk_text}"` — 76,768 rows
  - Batch 100, rate-limit retry with exponential backoff, resumable
- [x] Populate tsvector columns — 40,754 kp_fts rows + 4,885 ti_fts rows
- [x] Build HNSW indexes — key_points_full (101.7s), trade_ideas_full (2.1s), email_chunks (199.9s)
- [x] Verify — semantic query "Federal Reserve interest rates" returns correct Fed/rates key points from UBS, MNI

---

### ✅ Phase 3 — FastAPI Backend (COMPLETE)
**Branch:** `phase/3-backend`  
**Goal:** All API endpoints working, chat streaming working

**Tasks:**
- [x] `backend/app/main.py` — FastAPI app, CORS, lifespan
- [x] `backend/app/config.py` — env vars: OPENAI_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL
- [x] `backend/app/retrieval/hybrid.py` — hybrid search implementation
  - `search_key_points(query, filters, top_k)` → RRF of semantic + BM25
  - `search_trade_ideas(query, filters, top_k)`
  - `search_emails(query, filters, top_k)` → chunk ANN → deduplicate by `email_content_hash` → fetch parent emails → join related key points + trade ideas on same hash → return `{email, matched_chunk, related_key_points[], related_trade_ideas[]}`
  - Query expansion: alias resolution from source_orgs + geographies reference tables
- [x] `backend/app/routers/key_points.py` — browse + search endpoints
- [x] `backend/app/routers/trade_ideas.py`
- [x] `backend/app/routers/disagreements.py`
- [x] `backend/app/routers/summaries.py` — topic_summaries + trade_summaries
- [x] `backend/app/routers/emails.py` — viewer endpoint + raw .eml streaming
- [x] `backend/app/routers/meta.py` — topics, geographies, source_orgs lists
- [x] `backend/app/chat/tools.py` — 6 Claude tool definitions
- [x] `backend/app/chat/system_prompt.py` — system prompt with data model, approved entity lists, gotchas
- [x] `backend/app/routers/chat.py` — SSE streaming endpoint, tool loop (max 5 rounds)
- [x] Runtime bug fixes: `CAST(:x AS type)` instead of `::type`, BM25 WHERE clause, `::text = ANY()` for uuid arrays

---

### 🔲 Phase 4 — Frontend
**Branch:** `phase/4-frontend`  
**Goal:** Full browser UI working, chat + browser + email viewer

**Tasks:**
- [ ] `frontend/index.html` — base layout, Tailwind + Alpine.js CDN
- [ ] `frontend/js/api.js` — fetch wrapper for all backend endpoints
- [ ] `frontend/js/app.js` — Alpine.js state management
  - Tab state: Key Points | Trade Ideas | Disagreements | Summaries | Webinars
  - Filter state: date range, banks, topics, geos, sentiment
  - Mode: browse vs chat
  - Email viewer state: open/closed, current email hash
- [ ] `frontend/js/chat.js` — SSE streaming, message history, tool-call display
- [ ] Components (inline Alpine templates):
  - `key-point-card.html` — displays key point + metadata chips + "view email" button
  - `trade-idea-card.html` — trade idea + legs + asset class
  - `disagreement-card.html` — bank positions side-by-side, resolution status
  - `summary-card.html` — clickable bullets (footnote [N] opens key point viewer)
  - `email-viewer.html` — slide panel, citation highlighted, download button
  - `filter-panel.html` — date pickers, multi-select dropdowns for banks/topics/geos
  - `chat-panel.html` — message list, streaming input, source cards
- [ ] Use Playwright MCP to verify UI during development

---

### 🔲 Phase 5 — Polish + Team Deploy
**Branch:** `phase/5-deploy`  
**Goal:** Deployable to team, running on Supabase + Railway + Vercel

**Tasks:**
- [ ] Supabase project setup (managed Postgres + pgvector)
- [ ] Run migration + embedding scripts against Supabase
- [ ] Railway deploy: backend Docker container
- [ ] Vercel deploy: frontend static files
- [ ] Auth: simple API key header or Supabase Auth (TBD based on team need)
- [ ] README with setup instructions

---

## Git Commit Convention

**Rule: commit at every meaningful milestone — not just "when done".**

A milestone is any of:
- A file or module is written and the code runs without errors
- A phase task is checked off
- A bug is fixed
- A schema migration is applied and verified
- A script produces verified output

### Commit message format
```
<type>: <short description>

<optional body — what changed and why, not how>
```

**Types:** `feat`, `fix`, `chore`, `refactor`, `docs`

### Examples
```
feat: add alembic migration 001 — creates all 12 tables + indexes

feat: implement migrate.py with per-table stats reporting

fix: change Docker host port to 5433 to avoid conflict with local Postgres

feat: generate OpenAI embeddings for key_points_full and trade_ideas_full

chore: add .gitignore entries for .env, __pycache__, data/postgres
```

### When to commit
| Milestone | Commit? |
|---|---|
| New file written and imports work | Yes |
| `alembic upgrade head` succeeds | Yes |
| `migrate.py` run completes with verified counts | Yes |
| Phase complete (all tasks checked) | Yes — tag as `phase-1-complete` |
| Mid-task edit that doesn't run yet | No — wait until it works |
| Stash/WIP state | No — finish the task first |

---

## Key Design Decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| No SCD-2 in new DB | filter load_end_dt IS NULL during migration | Simpler schema, this is static historical data |
| Email body in Postgres | store email_body from emails_parsed.csv | No S3 needed, text-only content, fast API |
| Two retrieval paths | key-point path + email chunk path | Complementary coverage — structured intelligence vs broad search |
| Embed citation in chunk | `text + citation + context` for key points | Citation adds verbatim domain jargon that improves recall |
| RRF for hybrid fusion | reciprocal rank fusion | Parameter-free, robust, no retraining needed |
| Alpine.js frontend | no build step, tiny (15KB) | Quick iteration, no toolchain, easy to modify |
| Separate git repo | `email-ai/macro-rag/` | Old code untouched, new code independently versioned |

---

## Questions / Decisions Pending

- [ ] Auth for team deployment: API key? Supabase Auth? Basic auth?
- [ ] `raw-emails` for deployed version: do all team members have local copies, or serve from backend only?
- [ ] Filters to expose for trade idea `legs` (instrument, direction) — complex JSONB queries, defer to v2?
- [ ] Should topic_summaries show ALL dates or only most recent per topic?

---

## Gotchas to Remember

1. `emails_parsed.csv` has ~637k rows but most are SCD-2 duplicates — always filter `load_end_dt IS NULL` AND `status = 'ok'` before dedup by email_content_hash
2. `key_points.source_org = 'Others'` → real bank name is in `suggested_source_org` → use `effective_source_org` in all queries
3. `label_map` in topic_summaries maps footnote labels (string `"[25]"`) → key_point_id (UUID string) — parse as JSON dict
4. `bank_positions` in disagreements is a JSON array — needs to be parsed as JSONB
5. `key_point_citation` is always a verbatim substring of `email_body` — use for highlighting (no fuzzy matching needed)
6. email_content_hash is the stable join key between key_points and emails_parsed (file_id is a dead SharePoint ID)
7. `geographies` uses ISO-style codes (CHN, AUS, GBR) plus region codes (EM, EMEA, DM, Global) — see geographies_approved for full list
8. Trade idea `legs` column is VARIANT in Databricks → stored as JSON string in CSV → parse to JSONB in Postgres
