from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["summaries"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/topic-summaries")
async def list_topic_summaries(
    db: Db,
    topic: str | None = None,
    date: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}

    if topic:
        filters.append("topic = :topic")
        params["topic"] = topic
    if date:
        filters.append("window_start::date <= :date AND window_end::date >= :date")
        params["date"] = date

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    data_sql = text(f"""
        SELECT id, topic, window_start, window_end, bullets, bullet_count,
               source_orgs, kp_count, label_map
        FROM topic_summaries {where}
        ORDER BY window_end DESC, topic
        LIMIT :limit OFFSET :offset
    """)
    count_sql = text(f"SELECT count(*) FROM topic_summaries {where}")

    total = (await db.execute(count_sql, params)).scalar()
    rows = await db.execute(data_sql, params)
    cols = ["id", "topic", "window_start", "window_end", "bullets",
            "bullet_count", "source_orgs", "kp_count", "label_map"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"data": data, "total": total, "page": page, "limit": limit}


@router.get("/trade-summaries")
async def list_trade_summaries(
    db: Db,
    asset_class: str | None = None,
    date: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}

    if asset_class:
        filters.append("group_key = :asset_class")
        params["asset_class"] = asset_class
    if date:
        filters.append("window_start::date <= :date AND window_end::date >= :date")
        params["date"] = date

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    data_sql = text(f"""
        SELECT id, group_key, window_start, window_end, bullets, bullet_count,
               source_orgs, kp_count, label_map
        FROM trade_summaries {where}
        ORDER BY window_end DESC, group_key
        LIMIT :limit OFFSET :offset
    """)
    count_sql = text(f"SELECT count(*) FROM trade_summaries {where}")

    total = (await db.execute(count_sql, params)).scalar()
    rows = await db.execute(data_sql, params)
    cols = ["id", "group_key", "window_start", "window_end", "bullets",
            "bullet_count", "source_orgs", "kp_count", "label_map"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"data": data, "total": total, "page": page, "limit": limit}
