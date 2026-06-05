# Macro RAG — Full Project Plan

**Last updated:** 2026-06-05  
**Status:** Phase 0 — Planning complete, starting Phase 1  
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
| `emails_parsed.csv` | ~637k (many SCD-2 dups) | email_content_hash, file_name, email_subject, email_from, email_sent_dt, email_body, email_body_length |
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

### Tools

| Tool | Input | Retrieval path | Returns |
|---|---|---|---|
| `search_key_points` | query, source_orgs?, topics?, geographies?, sentiment?, date_range?, time_reference? | Path 1 hybrid | top-20 key points with metadata |
| `search_trade_ideas` | query, source_orgs?, asset_class?, geographies?, time_horizon?, date_range? | Path 1 hybrid | top-20 trade ideas with metadata |
| `search_emails` | query, source_org?, date_range? | Path 2 chunk retrieval | matching email chunks + parent email |
| `get_disagreements` | topic?, geography?, scale?, date_range?, confirmed_only=true | SQL structured | validated disagreements with bank_analysis |
| `get_topic_summary` | topic, date? | SQL exact match | pre-computed bullets with clickable [N] footnotes |
| `get_stats` | metric (count_by_bank, sentiment_distribution, topic_frequency), filters? | SQL aggregation | structured counts/distributions |

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

**UI flow on click:**
1. Slide-in right panel shows:
   - Key point / chunk text (top)
   - Email metadata: Subject, From, Date
   - Full email body with citation highlighted and scrolled into view
   - Action buttons: "Download .eml" (streams raw file from backend) | "Copy citation"

**Backend endpoint:**
- `GET /api/emails/{hash}` → JSON with email_body, subject, from, date, file_name
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
GET  /api/emails/{hash}           email body + metadata for viewer
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
- [x] Design retrieval architecture
- [x] Design database schema
- [x] Create `macro-rag` git repo
- [x] Write this plan

---

### 🔲 Phase 1 — Postgres + Data Migration
**Branch:** `phase/1-migration`  
**Goal:** All data loaded into local Postgres, queryable

**Tasks:**
- [ ] `docker-compose.yml` — Postgres 16 + pgvector extension
- [ ] `backend/pyproject.toml` — FastAPI, SQLAlchemy async, asyncpg, psycopg2, alembic, pandas, openai, anthropic
- [ ] `backend/app/db.py` — async SQLAlchemy engine + session factory
- [ ] `backend/app/models/` — ORM models for all tables
- [ ] `backend/scripts/migrate.py` — reads all CSVs from `../raw-data/`, deduplicates (load_end_dt IS NULL), joins enrichments into denormalized tables, loads into Postgres
  - emails: deduplicate by email_content_hash (largest email_body_length wins ties)
  - key_points_full: join key_points + key_points_enrichments on key_point_id/keypoint_id
  - trade_ideas_full: join trade_ideas + trade_ideas_enrichments on trade_idea_id
  - disagreements + disagreement_validations: filter to canonical/non-false-positive
  - topic_summaries, trade_summaries, webinars: deduplicate by entity key
  - source_orgs, topics, geographies: load reference tables
- [ ] `alembic/` — migration for schema creation (all tables + indexes, pgvector extension)
- [ ] Verify: run counts, spot-check joins, assert no nulls on key fields

**Dedup logic for emails_parsed (637k rows → ~5k unique):**
```python
# Keep the row with largest email_body_length per email_content_hash
# where load_end_dt IS NULL (or null) and status = 'ok'
emails_df = (
    df[df['status'] == 'ok']
    .sort_values('email_body_length', ascending=False)
    .drop_duplicates(subset=['email_content_hash'], keep='first')
)
```

---

### 🔲 Phase 2 — Embeddings + Chunking
**Branch:** `phase/2-embeddings`  
**Goal:** All vectors populated, both retrieval paths ready

**Tasks:**
- [ ] `backend/scripts/embed.py` — generate embeddings for key_points_full
  - Embed: `key_point_text + " Evidence: " + key_point_citation + " Context: " + key_point_context`
  - Batch: 100 at a time, rate-limit aware
  - Model: `text-embedding-3-small` (OpenAI, 1536-dim)
  - Update `key_points_full.kp_embedding`
- [ ] Same for trade_ideas_full (embed: text + citation + context)
- [ ] `backend/scripts/chunk_emails.py` — generate email chunks (Path 2)
  - For each unique email in `emails` table
  - Split body by paragraph (`\n\n`), merge small, split large
  - Target 200–350 tokens (estimate with `len(text.split()) * 1.3`)
  - Insert into `email_chunks` table
  - Generate embeddings for each chunk
  - Infer `source_org` from key_points with same email_content_hash (most common source_org)
- [ ] Populate tsvector columns (generated, done by DB trigger or update)
- [ ] Build all HNSW + GIN + btree indexes
- [ ] Verify: test a semantic search query end-to-end

---

### 🔲 Phase 3 — FastAPI Backend
**Branch:** `phase/3-backend`  
**Goal:** All API endpoints working, chat streaming working

**Tasks:**
- [ ] `backend/app/main.py` — FastAPI app, CORS, lifespan
- [ ] `backend/app/config.py` — env vars: OPENAI_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL
- [ ] `backend/app/retrieval/hybrid.py` — hybrid search implementation
  - `search_key_points(query, filters, top_k)` → RRF of semantic + BM25
  - `search_trade_ideas(query, filters, top_k)`
  - `search_emails(query, filters, top_k)` → chunk search → parent email
  - Query expansion: alias resolution from source_orgs + geographies reference tables
- [ ] `backend/app/routers/key_points.py` — browse + search endpoints
- [ ] `backend/app/routers/trade_ideas.py`
- [ ] `backend/app/routers/disagreements.py`
- [ ] `backend/app/routers/summaries.py` — topic_summaries + trade_summaries
- [ ] `backend/app/routers/emails.py` — viewer endpoint + raw .eml streaming
  - Raw .eml path: `../raw-emails/{MM}/{DD}/{file_name}` (relative to backend/)
- [ ] `backend/app/routers/meta.py` — topics, geographies, source_orgs lists
- [ ] `backend/app/chat/tools.py` — Claude tool definitions (6 tools, see schema above)
- [ ] `backend/app/chat/system_prompt.py` — system prompt with data model description, gotchas, approved entity lists
- [ ] `backend/app/routers/chat.py` — SSE streaming endpoint, tool loop
- [ ] Integration test: curl each endpoint, verify data shapes

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
