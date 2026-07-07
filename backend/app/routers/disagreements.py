from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["disagreements"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_disagreements(
    db: Db,
    topic: list[str] | None = Query(default=None),
    geo: list[str] | None = Query(default=None),
    scale: list[str] | None = Query(default=None),
    date_from: str | None = None,
    date_to: str | None = None,
    confirmed_only: bool = True,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}

    if confirmed_only:
        # Only disagreements that have a validation and are not false positives
        filters.append("""
            disagreement_id IN (
                SELECT disagreement_id FROM disagreement_validations
                WHERE is_false_positive = false
            )
        """)
    if topic:
        filters.append("group_key = ANY(:topic)")
        params["topic"] = topic
    if geo:
        filters.append("geography = ANY(:geo)")
        params["geo"] = geo
    if scale:
        filters.append("scale = ANY(:scale)")
        params["scale"] = scale
    if date_from:
        filters.append("window_end >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("window_start <= :date_to")
        params["date_to"] = date_to

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    validation_filter = "AND is_false_positive = false" if confirmed_only else ""
    count_sql = text(f"SELECT count(*) FROM disagreements {where}")
    data_sql = text(f"""
        SELECT d.disagreement_id, d.group_key, d.geography, d.window_start, d.window_end,
               d.scale, d.n_banks, d.sentiment_spread, d.bank_positions,
               v.resolution_summary, v.agent_confidence, v.is_false_positive, v.bank_analysis
        FROM disagreements d
        LEFT JOIN LATERAL (
            SELECT resolution_summary, agent_confidence, is_false_positive, bank_analysis
            FROM disagreement_validations
            WHERE disagreement_id = d.disagreement_id {validation_filter}
            ORDER BY agent_confidence DESC NULLS LAST
            LIMIT 1
        ) v ON true
        {where}
        ORDER BY d.window_end DESC, d.scale DESC
        LIMIT :limit OFFSET :offset
    """)

    total = (await db.execute(count_sql, params)).scalar()
    rows = await db.execute(data_sql, params)
    cols = ["disagreement_id", "group_key", "geography", "window_start", "window_end",
            "scale", "n_banks", "sentiment_spread", "bank_positions",
            "resolution_summary", "agent_confidence", "is_false_positive", "bank_analysis"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"data": data, "total": total, "page": page, "limit": limit}


@router.get("/{disagreement_id}")
async def get_disagreement(disagreement_id: str, db: Db) -> dict[str, Any]:
    d_row = await db.execute(text("""
        SELECT * FROM disagreements WHERE disagreement_id = CAST(:id AS uuid)
    """), {"id": disagreement_id})
    d = d_row.fetchone()
    if not d:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Disagreement not found")

    v_rows = await db.execute(text("""
        SELECT * FROM disagreement_validations
        WHERE disagreement_id = CAST(:id AS uuid)
        ORDER BY agent_confidence DESC NULLS LAST
        LIMIT 1
    """), {"id": disagreement_id})
    v = v_rows.fetchone()

    return {
        "disagreement": dict(d._mapping),
        "validation": dict(v._mapping) if v else None,
    }
