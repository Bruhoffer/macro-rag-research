from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.retrieval.hybrid import search_trade_ideas

router = APIRouter(tags=["trade-ideas"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_trade_ideas(
    db: Db,
    q: str | None = None,
    source_org: list[str] | None = Query(default=None),
    asset_class: list[str] | None = Query(default=None),
    geo: list[str] | None = Query(default=None),
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    if q:
        results = await search_trade_ideas(
            db, q,
            source_orgs=source_org,
            asset_classes=asset_class,
            geographies=geo,
            date_from=date_from,
            date_to=date_to,
            top_k=limit,
        )
        return {"data": [vars(r) for r in results], "total": len(results), "page": page, "limit": limit}

    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}
    if source_org:
        filters.append("effective_source_org = ANY(:source_org)")
        params["source_org"] = source_org
    if asset_class:
        filters.append("asset_class = ANY(:asset_class)")
        params["asset_class"] = asset_class
    if geo:
        filters.append("geographies && :geo")
        params["geo"] = geo
    if date_from:
        filters.append("email_sent_dt >= :date_from")
        params["date_from"] = date.fromisoformat(date_from)
    if date_to:
        filters.append("email_sent_dt <= :date_to")
        params["date_to"] = date.fromisoformat(date_to)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    count_sql = text(f"SELECT count(*) FROM trade_ideas_full {where}")
    data_sql = text(f"""
        SELECT trade_idea_id, email_content_hash, email_sent_dt, email_subject,
               file_name, effective_source_org, trade_idea_text, trade_idea_citation,
               asset_class, time_horizon, geographies, target_price, stop_price,
               trigger_condition, legs
        FROM trade_ideas_full {where}
        ORDER BY email_sent_dt DESC
        LIMIT :limit OFFSET :offset
    """)

    total = (await db.execute(count_sql, params)).scalar()
    rows = await db.execute(data_sql, params)
    cols = ["trade_idea_id", "email_content_hash", "email_sent_dt", "email_subject",
            "file_name", "effective_source_org", "trade_idea_text", "trade_idea_citation",
            "asset_class", "time_horizon", "geographies", "target_price", "stop_price",
            "trigger_condition", "legs"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"data": data, "total": total, "page": page, "limit": limit}


@router.get("/{trade_idea_id}")
async def get_trade_idea(trade_idea_id: str, db: Db) -> dict[str, Any]:
    row = await db.execute(text("""
        SELECT ti.*, e.email_body, e.email_from
        FROM trade_ideas_full ti
        JOIN emails e ON e.email_content_hash = ti.email_content_hash
        WHERE ti.trade_idea_id = :id
    """), {"id": trade_idea_id})
    r = row.fetchone()
    if not r:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade idea not found")
    return dict(r._mapping)
