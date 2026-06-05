from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.retrieval.hybrid import search_key_points

router = APIRouter(tags=["key-points"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_key_points(
    db: Db,
    q: str | None = None,
    source_org: list[str] | None = Query(default=None),
    topic: list[str] | None = Query(default=None),
    geo: list[str] | None = Query(default=None),
    sentiment: list[str] | None = Query(default=None),
    date_from: str | None = None,
    date_to: str | None = None,
    time_reference: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    if q:
        sentiment_min, sentiment_max = _sentiment_range(sentiment)
        results = await search_key_points(
            db, q,
            source_orgs=source_org,
            topics=topic,
            geographies=geo,
            sentiment_min=sentiment_min,
            sentiment_max=sentiment_max,
            date_from=date_from,
            date_to=date_to,
            time_reference=time_reference,
            top_k=limit,
        )
        return {"data": [vars(r) for r in results], "total": len(results), "page": page, "limit": limit}

    # Browse mode — SQL with filters, no vector search
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}
    if source_org:
        filters.append("effective_source_org = ANY(:source_org)")
        params["source_org"] = source_org
    if topic:
        filters.append("topics && :topic")
        params["topic"] = topic
    if geo:
        filters.append("geographies && :geo")
        params["geo"] = geo
    if date_from:
        filters.append("email_sent_dt >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("email_sent_dt <= :date_to")
        params["date_to"] = date_to
    if time_reference:
        filters.append("time_reference = :time_reference")
        params["time_reference"] = time_reference
    if sentiment:
        min_, max_ = _sentiment_range(sentiment)
        if min_ is not None:
            filters.append("sentiment_score >= :smin")
            params["smin"] = min_
        if max_ is not None:
            filters.append("sentiment_score <= :smax")
            params["smax"] = max_

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    count_sql = text(f"SELECT count(*) FROM key_points_full {where}")
    data_sql = text(f"""
        SELECT key_point_id, email_content_hash, email_sent_dt, email_subject,
               file_name, source_org, effective_source_org,
               key_point_text, key_point_citation, topics, geographies,
               sentiment, sentiment_score, time_reference, future_time_horizon
        FROM key_points_full {where}
        ORDER BY email_sent_dt DESC
        LIMIT :limit OFFSET :offset
    """)

    total = (await db.execute(count_sql, params)).scalar()
    rows = await db.execute(data_sql, params)
    cols = ["key_point_id", "email_content_hash", "email_sent_dt", "email_subject",
            "file_name", "source_org", "effective_source_org",
            "key_point_text", "key_point_citation", "topics", "geographies",
            "sentiment", "sentiment_score", "time_reference", "future_time_horizon"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"data": data, "total": total, "page": page, "limit": limit}


@router.get("/{key_point_id}")
async def get_key_point(key_point_id: str, db: Db) -> dict[str, Any]:
    row = await db.execute(text("""
        SELECT kp.*, e.email_body, e.email_from
        FROM key_points_full kp
        JOIN emails e ON e.email_content_hash = kp.email_content_hash
        WHERE kp.key_point_id = CAST(:id AS uuid)
    """), {"id": key_point_id})
    r = row.fetchone()
    if not r:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Key point not found")
    return dict(r._mapping)


def _sentiment_range(sentiments: list[str] | None) -> tuple[int | None, int | None]:
    if not sentiments:
        return None, None
    score_map = {"very bearish": -2, "bearish": -1, "neutral": 0, "bullish": 1, "very bullish": 2}
    scores = [score_map[s] for s in sentiments if s in score_map]
    return (min(scores), max(scores)) if scores else (None, None)
