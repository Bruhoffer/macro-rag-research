"""
Phase 2 — Generate embeddings for key_points_full, trade_ideas_full, email_chunks.
Also populates tsvector columns and builds HNSW indexes.

Run from backend/:
    python scripts/embed.py                     # embed all tables + tsvector + hnsw
    python scripts/embed.py --table key_points  # just key_points_full
    python scripts/embed.py --table trade_ideas
    python scripts/embed.py --table chunks
    python scripts/embed.py --tsvector-only     # update tsvectors only, no embedding
    python scripts/embed.py --hnsw-only         # build HNSW indexes only
    python scripts/embed.py --verify            # run a test semantic query after embedding

Resumable: rows where embedding IS NOT NULL are skipped. Re-run any time after interruption.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector
from tqdm import tqdm

load_dotenv(Path(__file__).parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL_SYNC"]
EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 100

oai: OpenAI | None = None  # initialised in main() after key check


# ── helpers ────────────────────────────────────────────────────────────────────

def get_conn():
    conn = psycopg2.connect(DB_URL)
    register_vector(conn)
    return conn


def embed_batch(texts: list[str]) -> list[np.ndarray]:
    """Call OpenAI embeddings API. Returns list of float32 numpy arrays. Retries on error."""
    for attempt in range(5):
        try:
            resp = oai.embeddings.create(model=EMBED_MODEL, input=texts)
            return [np.array(e.embedding, dtype=np.float32) for e in resp.data]
        except Exception as exc:
            if attempt == 4:
                raise
            wait = 2 ** attempt
            tqdm.write(f"  OpenAI error ({exc}), retrying in {wait}s...")
            time.sleep(wait)


def embed_table(
    conn,
    *,
    label: str,
    table: str,
    id_col: str,
    embed_col: str,
    fetch_sql: str,
    build_text,
):
    """Generic embedding loop for one table.

    fetch_sql must be: SELECT id_col, <text cols...> FROM table WHERE id_col = ANY(%s)
    build_text is called with each fetched row tuple and returns the string to embed.
    Commits after every batch so the run is resumable on interruption.
    """
    cur = conn.cursor()
    cur.execute(
        f"SELECT {id_col} FROM {table} WHERE {embed_col} IS NULL ORDER BY {id_col}"
    )
    ids = [r[0] for r in cur.fetchall()]

    if not ids:
        print(f"{label}: already fully embedded, skipping")
        return

    print(f"{label}: {len(ids):,} rows to embed")
    for i in tqdm(range(0, len(ids), BATCH_SIZE), desc=label, unit="batch"):
        batch_ids = ids[i : i + BATCH_SIZE]
        cur.execute(fetch_sql, (batch_ids,))
        rows = cur.fetchall()
        texts = [build_text(r) for r in rows]
        embeddings = embed_batch(texts)
        psycopg2.extras.execute_batch(
            cur,
            f"UPDATE {table} SET {embed_col} = %s WHERE {id_col} = %s",
            [(emb, row[0]) for emb, row in zip(embeddings, rows)],
            page_size=BATCH_SIZE,
        )
        conn.commit()


# ── per-table embedding functions ──────────────────────────────────────────────

def embed_key_points(conn):
    embed_table(
        conn,
        label="key_points_full",
        table="key_points_full",
        id_col="key_point_id",
        embed_col="kp_embedding",
        fetch_sql=(
            "SELECT key_point_id, key_point_text, key_point_citation, key_point_context "
            "FROM key_points_full WHERE key_point_id = ANY(%s)"
        ),
        build_text=lambda r: (
            f"{r[1] or ''} Evidence: {r[2] or ''} Context: {r[3] or ''}"
        ),
    )


def embed_trade_ideas(conn):
    embed_table(
        conn,
        label="trade_ideas_full",
        table="trade_ideas_full",
        id_col="trade_idea_id",
        embed_col="ti_embedding",
        fetch_sql=(
            "SELECT trade_idea_id, trade_idea_text, trade_idea_citation, trade_idea_context "
            "FROM trade_ideas_full WHERE trade_idea_id = ANY(%s)"
        ),
        build_text=lambda r: (
            f"{r[1] or ''} Evidence: {r[2] or ''} Context: {r[3] or ''}"
        ),
    )


def embed_chunks(conn):
    # Contextual Retrieval (Anthropic, 2024): prepend document-level metadata to each chunk
    # so the vector captures *which email* the chunk came from, not just the raw text.
    # email_chunks already has source_org, email_sent_dt, email_subject denormalised in it.
    embed_table(
        conn,
        label="email_chunks",
        table="email_chunks",
        id_col="chunk_id",
        embed_col="chunk_embedding",
        fetch_sql=(
            "SELECT chunk_id, chunk_text, source_org, email_sent_dt, email_subject "
            "FROM email_chunks WHERE chunk_id = ANY(%s)"
        ),
        build_text=lambda r: (
            f"Email from {r[2] or 'Unknown'} "
            f"({r[3].date() if r[3] else 'unknown date'}, "
            f"subject: '{r[4] or ''}'):\n\n{r[1] or ''}"
        ),
    )


# ── tsvector + hnsw ────────────────────────────────────────────────────────────

def update_tsvectors(conn):
    cur = conn.cursor()
    print("\nUpdating tsvector columns...")

    cur.execute("""
        UPDATE key_points_full
        SET kp_fts = to_tsvector('english',
            coalesce(key_point_text, '') || ' ' ||
            coalesce(key_point_citation, '') || ' ' ||
            coalesce(key_point_context, '')
        )
        WHERE kp_fts IS NULL
    """)
    print(f"  key_points_full:  {cur.rowcount:,} rows")
    conn.commit()

    cur.execute("""
        UPDATE trade_ideas_full
        SET ti_fts = to_tsvector('english',
            coalesce(trade_idea_text, '') || ' ' ||
            coalesce(trade_idea_citation, '') || ' ' ||
            coalesce(trade_idea_context, '')
        )
        WHERE ti_fts IS NULL
    """)
    print(f"  trade_ideas_full: {cur.rowcount:,} rows")
    conn.commit()


def build_hnsw(conn):
    cur = conn.cursor()
    print("\nBuilding HNSW indexes (may take several minutes)...")
    indexes = [
        ("key_points_full",  "ix_kp_hnsw", "kp_embedding"),
        ("trade_ideas_full", "ix_ti_hnsw", "ti_embedding"),
        ("email_chunks",     "ix_ec_hnsw", "chunk_embedding"),
    ]
    for table, ix_name, col in indexes:
        print(f"  {table}...", end=" ", flush=True)
        t = time.time()
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {ix_name} ON {table}
            USING hnsw ({col} vector_cosine_ops)
            WITH (m=16, ef_construction=64)
        """)
        conn.commit()
        print(f"done ({time.time() - t:.1f}s)")


# ── verification ───────────────────────────────────────────────────────────────

def verify(conn):
    query = "Federal Reserve interest rates"
    print(f'\nVerification — nearest key points to "{query}":')
    resp = oai.embeddings.create(model=EMBED_MODEL, input=[query])
    q_emb = np.array(resp.data[0].embedding, dtype=np.float32)
    cur = conn.cursor()
    cur.execute("""
        SELECT key_point_text, effective_source_org, email_sent_dt::date
        FROM key_points_full
        ORDER BY kp_embedding <=> %s
        LIMIT 5
    """, (q_emb,))
    for row in cur.fetchall():
        print(f"  [{row[1]} | {row[2]}] {row[0][:120]}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    global oai

    parser = argparse.ArgumentParser(description="Embed and index macro RAG tables")
    parser.add_argument(
        "--table",
        choices=["key_points", "trade_ideas", "chunks", "all"],
        default="all",
        help="Which table to embed (default: all)",
    )
    parser.add_argument("--tsvector-only", action="store_true", help="Only update tsvectors, skip embedding")
    parser.add_argument("--hnsw-only", action="store_true", help="Only build HNSW indexes, skip embedding")
    parser.add_argument("--verify", action="store_true", help="Run a test semantic query after embedding")
    args = parser.parse_args()

    needs_oai = not (args.tsvector_only or args.hnsw_only) or args.verify
    if needs_oai:
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key or key == "your_openai_api_key_here":
            print("ERROR: OPENAI_API_KEY is not set in .env", file=sys.stderr)
            sys.exit(1)
        oai = OpenAI(api_key=key)

    conn = get_conn()

    if args.tsvector_only:
        update_tsvectors(conn)
    elif args.hnsw_only:
        build_hnsw(conn)
    else:
        if args.table in ("key_points", "all"):
            embed_key_points(conn)
        if args.table in ("trade_ideas", "all"):
            embed_trade_ideas(conn)
        if args.table in ("chunks", "all"):
            embed_chunks(conn)
        update_tsvectors(conn)
        build_hnsw(conn)

    if args.verify:
        verify(conn)

    conn.close()
    print("\nPhase 2 complete.")


if __name__ == "__main__":
    main()
