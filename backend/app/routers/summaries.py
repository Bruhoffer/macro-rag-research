from datetime import date as date_type
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
        params["date"] = date_type.fromisoformat(date)

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

    all_kp_ids: list[str] = []
    for s in data:
        all_kp_ids.extend((s.get("label_map") or {}).values())

    if all_kp_ids:
        enrich_rows = await db.execute(
            text("""
                SELECT key_point_id, email_content_hash, key_point_citation,
                       effective_source_org, email_sent_dt
                FROM key_points_full WHERE key_point_id::text = ANY(:ids)
            """),
            {"ids": all_kp_ids},
        )
        kp_meta: dict[str, dict] = {
            str(r[0]): {
                "key_point_id": str(r[0]),
                "email_content_hash": r[1],
                "key_point_citation": r[2],
                "effective_source_org": r[3],
                "email_sent_dt": str(r[4]) if r[4] else None,
            }
            for r in enrich_rows
        }
        for s in data:
            lm = s.get("label_map") or {}
            s["label_map_enriched"] = {
                label: kp_meta[kp_id]
                for label, kp_id in lm.items()
                if kp_id in kp_meta
            }
    else:
        for s in data:
            s["label_map_enriched"] = {}

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
        params["date"] = date_type.fromisoformat(date)

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

    all_ti_ids: list[str] = []
    for s in data:
        all_ti_ids.extend((s.get("label_map") or {}).values())

    if all_ti_ids:
        enrich_rows = await db.execute(
            text("""
                SELECT trade_idea_id, email_content_hash, trade_idea_citation,
                       effective_source_org, email_sent_dt
                FROM trade_ideas_full WHERE trade_idea_id::text = ANY(:ids)
            """),
            {"ids": all_ti_ids},
        )
        ti_meta: dict[str, dict] = {
            str(r[0]): {
                "trade_idea_id": str(r[0]),
                "email_content_hash": r[1],
                "trade_idea_citation": r[2],
                "effective_source_org": r[3],
                "email_sent_dt": str(r[4]) if r[4] else None,
            }
            for r in enrich_rows
        }
        for s in data:
            lm = s.get("label_map") or {}
            s["label_map_enriched"] = {
                label: ti_meta[ti_id]
                for label, ti_id in lm.items()
                if ti_id in ti_meta
            }
    else:
        for s in data:
            s["label_map_enriched"] = {}

    return {"data": data, "total": total, "page": page, "limit": limit}
