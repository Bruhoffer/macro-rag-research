"""
Hybrid retrieval engine — two complementary paths.

Path 1 (key_points / trade_ideas):
  SQL pre-filter → pgvector ANN (cosine) + tsvector BM25 → Reciprocal Rank Fusion (k=60)

Path 2 (email_chunks):
  pgvector ANN → deduplicate by email_content_hash → fetch parent emails
  → join related key_points + trade_ideas from same email

Query expansion:
  "Goldman" → "GS", "China" → ["CHN", "EM"] resolved from reference tables at startup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBED_MODEL, OPENAI_API_KEY

_oai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# RRF constant — standard default, controls how much top ranks dominate
RRF_K = 60


# ── query expansion tables (loaded once at startup via load_aliases) ───────────

_org_aliases: dict[str, str] = {}       # "goldman" → "GS"
_geo_aliases: dict[str, str] = {}       # "china" → "CHN"


async def load_aliases(db: AsyncSession) -> None:
    """Call once at app startup to populate alias lookup tables."""
    rows = await db.execute(text(
        "SELECT org_shortform_name, org_aliases FROM source_orgs WHERE org_aliases IS NOT NULL"
    ))
    for shortform, aliases in rows:
        if aliases:
            for alias in aliases:
                _org_aliases[alias.lower()] = shortform

    rows = await db.execute(text(
        "SELECT geography_name, description FROM geographies"
    ))
    for name, _desc in rows:
        _geo_aliases[name.lower()] = name


def expand_orgs(names: list[str]) -> list[str]:
    """Resolve aliases: ["Goldman", "GS"] → ["GS"]"""
    out = set()
    for n in names:
        resolved = _org_aliases.get(n.lower(), n.upper())
        out.add(resolved)
    return list(out)


def expand_geos(names: list[str]) -> list[str]:
    out = set()
    for n in names:
        resolved = _geo_aliases.get(n.lower(), n.upper())
        out.add(resolved)
    return list(out)


# ── embedding ──────────────────────────────────────────────────────────────────

async def embed_query(text_: str) -> list[float]:
    resp = await _oai.embeddings.create(model=EMBED_MODEL, input=[text_])
    return resp.data[0].embedding


# ── RRF fusion ─────────────────────────────────────────────────────────────────

def rrf(lists: list[list[str]], weights: list[float], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    score(d) = sum_i( weight_i / (k + rank_i(d)) )
    Returns IDs ordered by descending fused score.
    """
    scores: dict[str, float] = {}
    for ranked, w in zip(lists, weights):
        for rank, id_ in enumerate(ranked, start=1):
            scores[id_] = scores.get(id_, 0.0) + w / (k + rank)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


# ── Path 1: key points ─────────────────────────────────────────────────────────

@dataclass
class KeyPointResult:
    key_point_id: str
    email_content_hash: str
    email_sent_dt: Any
    email_subject: str
    file_name: str
    source_org: str
    effective_source_org: str
    key_point_text: str
    key_point_citation: str
    key_point_context: str
    topics: list[str]
    geographies: list[str]
    sentiment: str
    sentiment_score: int
    time_reference: str
    future_time_horizon: str


async def search_key_points(
    db: AsyncSession,
    query: str,
    *,
    source_orgs: list[str] | None = None,
    topics: list[str] | None = None,
    geographies: list[str] | None = None,
    sentiment_min: int | None = None,
    sentiment_max: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    time_reference: str | None = None,
    top_k: int = 20,
) -> list[KeyPointResult]:
    embedding = await embed_query(query)
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
    tsquery = _to_tsquery(query)

    # Expand aliases
    orgs = expand_orgs(source_orgs) if source_orgs else None
    geos = expand_geos(geographies) if geographies else None

    filters, params = _build_filters(orgs, topics, geos, sentiment_min, sentiment_max, date_from, date_to, time_reference)

    candidate_limit = top_k * 10  # over-fetch before RRF

    ann_where = ("WHERE " + " AND ".join(filters)) if filters else ""
    bm25_where = "WHERE " + " AND ".join(["kp_fts @@ to_tsquery('english', :tsq)"] + filters)

    # ANN (semantic)
    ann_sql = text(f"""
        SELECT key_point_id::text
        FROM key_points_full
        {ann_where}
        ORDER BY kp_embedding <=> CAST(:emb AS vector)
        LIMIT :lim
    """)
    ann_rows = await db.execute(ann_sql, {**params, "emb": emb_str, "lim": candidate_limit})
    ann_ids = [r[0] for r in ann_rows]

    # BM25 (full-text)
    bm25_sql = text(f"""
        SELECT key_point_id::text
        FROM key_points_full
        {bm25_where}
        ORDER BY ts_rank(kp_fts, to_tsquery('english', :tsq)) DESC
        LIMIT :lim
    """)
    bm25_rows = await db.execute(bm25_sql, {**params, "tsq": tsquery, "lim": candidate_limit})
    bm25_ids = [r[0] for r in bm25_rows]

    # RRF — semantic weighted slightly higher
    fused_ids = rrf([ann_ids, bm25_ids], weights=[0.6, 0.4])[:top_k]
    if not fused_ids:
        return []

    # Fetch full records for the fused set
    fetch_sql = text("""
        SELECT key_point_id, email_content_hash, email_sent_dt, email_subject,
               file_name, source_org, effective_source_org,
               key_point_text, key_point_citation, key_point_context,
               topics, geographies, sentiment, sentiment_score,
               time_reference, future_time_horizon
        FROM key_points_full
        WHERE key_point_id::text = ANY(:ids)
    """)
    rows = await db.execute(fetch_sql, {"ids": fused_ids})
    by_id = {str(r[0]): r for r in rows}

    return [
        KeyPointResult(
            key_point_id=str(by_id[id_][0]),
            email_content_hash=by_id[id_][1],
            email_sent_dt=by_id[id_][2],
            email_subject=by_id[id_][3] or "",
            file_name=by_id[id_][4] or "",
            source_org=by_id[id_][5] or "",
            effective_source_org=by_id[id_][6] or "",
            key_point_text=by_id[id_][7] or "",
            key_point_citation=by_id[id_][8] or "",
            key_point_context=by_id[id_][9] or "",
            topics=by_id[id_][10] or [],
            geographies=by_id[id_][11] or [],
            sentiment=by_id[id_][12] or "",
            sentiment_score=by_id[id_][13] or 0,
            time_reference=by_id[id_][14] or "",
            future_time_horizon=by_id[id_][15] or "",
        )
        for id_ in fused_ids
        if id_ in by_id
    ]


# ── Path 1: trade ideas ────────────────────────────────────────────────────────

@dataclass
class TradeIdeaResult:
    trade_idea_id: str
    email_content_hash: str
    email_sent_dt: Any
    email_subject: str
    file_name: str
    effective_source_org: str
    trade_idea_text: str
    trade_idea_citation: str
    trade_idea_context: str
    asset_class: str
    time_horizon: str
    geographies: list[str]
    target_price: str
    stop_price: str
    trigger_condition: str
    legs: Any


async def search_trade_ideas(
    db: AsyncSession,
    query: str,
    *,
    source_orgs: list[str] | None = None,
    asset_classes: list[str] | None = None,
    geographies: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_k: int = 20,
) -> list[TradeIdeaResult]:
    embedding = await embed_query(query)
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
    tsquery = _to_tsquery(query)

    orgs = expand_orgs(source_orgs) if source_orgs else None
    geos = expand_geos(geographies) if geographies else None

    filters: list[str] = []
    params: dict[str, Any] = {}
    if orgs:
        filters.append("effective_source_org = ANY(:orgs)")
        params["orgs"] = orgs
    if asset_classes:
        filters.append("asset_class = ANY(:asset_classes)")
        params["asset_classes"] = asset_classes
    if geos:
        filters.append("geographies && :geos")
        params["geos"] = geos
    if date_from:
        filters.append("email_sent_dt >= :date_from")
        params["date_from"] = date.fromisoformat(date_from)
    if date_to:
        filters.append("email_sent_dt <= :date_to")
        params["date_to"] = date.fromisoformat(date_to)

    ann_where = ("WHERE " + " AND ".join(filters)) if filters else ""
    bm25_where = "WHERE " + " AND ".join(["ti_fts @@ to_tsquery('english', :tsq)"] + filters)
    candidate_limit = top_k * 10

    ann_sql = text(f"""
        SELECT trade_idea_id::text FROM trade_ideas_full
        {ann_where}
        ORDER BY ti_embedding <=> CAST(:emb AS vector) LIMIT :lim
    """)
    ann_rows = await db.execute(ann_sql, {**params, "emb": emb_str, "lim": candidate_limit})
    ann_ids = [r[0] for r in ann_rows]

    bm25_sql = text(f"""
        SELECT trade_idea_id::text FROM trade_ideas_full
        {bm25_where}
        ORDER BY ts_rank(ti_fts, to_tsquery('english', :tsq)) DESC
        LIMIT :lim
    """)
    bm25_rows = await db.execute(bm25_sql, {**params, "tsq": tsquery, "lim": candidate_limit})
    bm25_ids = [r[0] for r in bm25_rows]

    fused_ids = rrf([ann_ids, bm25_ids], weights=[0.6, 0.4])[:top_k]
    if not fused_ids:
        return []

    fetch_sql = text("""
        SELECT trade_idea_id, email_content_hash, email_sent_dt, email_subject,
               file_name, effective_source_org, trade_idea_text, trade_idea_citation,
               trade_idea_context, asset_class, time_horizon, geographies,
               target_price, stop_price, trigger_condition, legs
        FROM trade_ideas_full
        WHERE trade_idea_id::text = ANY(:ids)
    """)
    rows = await db.execute(fetch_sql, {"ids": fused_ids})
    by_id = {str(r[0]): r for r in rows}

    return [
        TradeIdeaResult(
            trade_idea_id=str(by_id[id_][0]),
            email_content_hash=by_id[id_][1],
            email_sent_dt=by_id[id_][2],
            email_subject=by_id[id_][3] or "",
            file_name=by_id[id_][4] or "",
            effective_source_org=by_id[id_][5] or "",
            trade_idea_text=by_id[id_][6] or "",
            trade_idea_citation=by_id[id_][7] or "",
            trade_idea_context=by_id[id_][8] or "",
            asset_class=by_id[id_][9] or "",
            time_horizon=by_id[id_][10] or "",
            geographies=by_id[id_][11] or [],
            target_price=by_id[id_][12] or "",
            stop_price=by_id[id_][13] or "",
            trigger_condition=by_id[id_][14] or "",
            legs=by_id[id_][15],
        )
        for id_ in fused_ids
        if id_ in by_id
    ]


# ── Path 2: email chunks → parent email + related insights ────────────────────

@dataclass
class RelatedKeyPoint:
    key_point_id: str
    key_point_text: str
    key_point_citation: str
    effective_source_org: str
    sentiment: str
    topics: list[str]


@dataclass
class RelatedTradeIdea:
    trade_idea_id: str
    trade_idea_text: str
    trade_idea_citation: str
    effective_source_org: str
    asset_class: str


@dataclass
class EmailResult:
    email_content_hash: str
    email_subject: str
    email_from: str
    email_sent_dt: Any
    file_name: str
    email_body: str
    matched_chunk: str                          # the chunk that matched the query
    related_key_points: list[RelatedKeyPoint]   # all kps from same email
    related_trade_ideas: list[RelatedTradeIdea] # all trade ideas from same email


async def search_emails(
    db: AsyncSession,
    query: str,
    *,
    source_orgs: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    top_k: int = 5,
) -> list[EmailResult]:
    embedding = await embed_query(query)
    emb_str = "[" + ",".join(str(x) for x in embedding) + "]"

    orgs = expand_orgs(source_orgs) if source_orgs else None

    filters: list[str] = []
    params: dict[str, Any] = {}
    if orgs:
        filters.append("source_org = ANY(:orgs)")
        params["orgs"] = orgs
    if date_from:
        filters.append("email_sent_dt >= :date_from")
        params["date_from"] = date.fromisoformat(date_from)
    if date_to:
        filters.append("email_sent_dt <= :date_to")
        params["date_to"] = date.fromisoformat(date_to)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    # ANN on chunks — fetch more, then dedup to top_k unique emails
    chunk_sql = text(f"""
        SELECT chunk_id, email_content_hash, chunk_text
        FROM email_chunks
        {where}
        ORDER BY chunk_embedding <=> CAST(:emb AS vector)
        LIMIT :lim
    """)
    chunk_rows = await db.execute(chunk_sql, {**params, "emb": emb_str, "lim": top_k * 5})

    # Keep one best chunk per email (first seen = highest ranked)
    seen: dict[str, str] = {}  # hash → matched_chunk
    for _chunk_id, email_hash, chunk_text in chunk_rows:
        if email_hash not in seen:
            seen[email_hash] = chunk_text or ""
        if len(seen) >= top_k:
            break

    if not seen:
        return []

    matched_hashes = list(seen.keys())

    # Fetch parent emails
    email_sql = text("""
        SELECT email_content_hash, email_subject, email_from,
               email_sent_dt, file_name, email_body
        FROM emails
        WHERE email_content_hash = ANY(:hashes)
    """)
    email_rows = await db.execute(email_sql, {"hashes": matched_hashes})
    emails_by_hash = {r[0]: r for r in email_rows}

    # Join related key points from same emails
    kp_sql = text("""
        SELECT email_content_hash, key_point_id, key_point_text,
               key_point_citation, effective_source_org, sentiment, topics
        FROM key_points_full
        WHERE email_content_hash = ANY(:hashes)
        ORDER BY email_content_hash, email_sent_dt
    """)
    kp_rows = await db.execute(kp_sql, {"hashes": matched_hashes})
    kps_by_hash: dict[str, list[RelatedKeyPoint]] = {}
    for h, kp_id, kp_text, citation, org, sentiment, topics in kp_rows:
        kps_by_hash.setdefault(h, []).append(RelatedKeyPoint(
            key_point_id=str(kp_id),
            key_point_text=kp_text or "",
            key_point_citation=citation or "",
            effective_source_org=org or "",
            sentiment=sentiment or "",
            topics=topics or [],
        ))

    # Join related trade ideas from same emails
    ti_sql = text("""
        SELECT email_content_hash, trade_idea_id, trade_idea_text,
               trade_idea_citation, effective_source_org, asset_class
        FROM trade_ideas_full
        WHERE email_content_hash = ANY(:hashes)
        ORDER BY email_content_hash, email_sent_dt
    """)
    ti_rows = await db.execute(ti_sql, {"hashes": matched_hashes})
    tis_by_hash: dict[str, list[RelatedTradeIdea]] = {}
    for h, ti_id, ti_text, citation, org, asset_class in ti_rows:
        tis_by_hash.setdefault(h, []).append(RelatedTradeIdea(
            trade_idea_id=str(ti_id),
            trade_idea_text=ti_text or "",
            trade_idea_citation=citation or "",
            effective_source_org=org or "",
            asset_class=asset_class or "",
        ))

    return [
        EmailResult(
            email_content_hash=h,
            email_subject=emails_by_hash[h][1] or "",
            email_from=emails_by_hash[h][2] or "",
            email_sent_dt=emails_by_hash[h][3],
            file_name=emails_by_hash[h][4] or "",
            email_body=emails_by_hash[h][5] or "",
            matched_chunk=seen[h],
            related_key_points=kps_by_hash.get(h, []),
            related_trade_ideas=tis_by_hash.get(h, []),
        )
        for h in matched_hashes
        if h in emails_by_hash
    ]


# ── helpers ────────────────────────────────────────────────────────────────────

def _to_tsquery(query: str) -> str:
    """Convert a free-text query to a Postgres tsquery string.

    Keeps only alphanumeric tokens, joins with ' & ' (AND).
    Short words / stop words that survive are fine — Postgres ignores them.
    """
    tokens = re.findall(r"[a-zA-Z0-9]+", query)
    if not tokens:
        return "macro"
    return " & ".join(tokens[:10])  # cap at 10 terms


def _build_filters(
    orgs: list[str] | None,
    topics: list[str] | None,
    geos: list[str] | None,
    sentiment_min: int | None,
    sentiment_max: int | None,
    date_from: str | None,
    date_to: str | None,
    time_reference: str | None,
) -> tuple[list[str], dict[str, Any]]:
    """Return (filter_clauses, params). Callers compose WHERE from the list."""
    filters: list[str] = []
    params: dict[str, Any] = {}

    if orgs:
        filters.append("effective_source_org = ANY(:orgs)")
        params["orgs"] = orgs
    if topics:
        filters.append("topics && :topics")
        params["topics"] = topics
    if geos:
        filters.append("geographies && :geos")
        params["geos"] = geos
    if sentiment_min is not None:
        filters.append("sentiment_score >= :smin")
        params["smin"] = sentiment_min
    if sentiment_max is not None:
        filters.append("sentiment_score <= :smax")
        params["smax"] = sentiment_max
    if date_from:
        filters.append("email_sent_dt >= :date_from")
        params["date_from"] = date.fromisoformat(date_from)
    if date_to:
        filters.append("email_sent_dt <= :date_to")
        params["date_to"] = date.fromisoformat(date_to)
    if time_reference:
        filters.append("time_reference = :time_reference")
        params["time_reference"] = time_reference

    return filters, params
