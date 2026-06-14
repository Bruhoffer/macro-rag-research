"""Admin / observability endpoints — read the trace tables for the /admin dashboard.

Mirrors the {data, total, page, limit} envelope used by the other routers.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["admin"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/chat-traces")
async def list_chat_traces(
    db: Db,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}
    if status:
        filters.append("ct.status = :status")
        params["status"] = status
    if date_from:
        filters.append("ct.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("ct.created_at <= :date_to")
        params["date_to"] = date_to

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    total = (await db.execute(text(f"SELECT count(*) FROM chat_traces ct {where}"), params)).scalar()
    rows = await db.execute(text(f"""
        SELECT ct.trace_id, ct.created_at, ct.user_query, ct.model, ct.n_rounds,
               ct.input_tokens, ct.output_tokens, ct.stop_reason, ct.status, ct.duration_ms,
               (SELECT count(*) FROM tool_call_traces t WHERE t.trace_id = ct.trace_id) AS tool_count
        FROM chat_traces ct
        {where}
        ORDER BY ct.created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)
    return {"data": [dict(r._mapping) for r in rows], "total": total, "page": page, "limit": limit}


@router.get("/chat-traces/{trace_id}")
async def get_chat_trace(trace_id: str, db: Db) -> dict[str, Any]:
    trow = (await db.execute(
        text("SELECT * FROM chat_traces WHERE trace_id = CAST(:id AS uuid)"),
        {"id": trace_id},
    )).fetchone()
    if not trow:
        raise HTTPException(status_code=404, detail="Trace not found")
    trace = dict(trow._mapping)
    tool_rows = await db.execute(text("""
        SELECT id, round_index, tool_name, tool_input, tool_output, result_count, duration_ms, created_at
        FROM tool_call_traces
        WHERE trace_id = CAST(:id AS uuid)
        ORDER BY round_index, created_at
    """), {"id": trace_id})
    trace["tool_calls"] = [dict(r._mapping) for r in tool_rows]
    return trace


@router.get("/api-requests")
async def list_api_requests(
    db: Db,
    path: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": (page - 1) * limit}
    if path:
        filters.append("path LIKE :path")
        params["path"] = f"%{path}%"
    if date_from:
        filters.append("created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("created_at <= :date_to")
        params["date_to"] = date_to

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    total = (await db.execute(text(f"SELECT count(*) FROM api_request_log {where}"), params)).scalar()
    rows = await db.execute(text(f"""
        SELECT id, created_at, method, path, query_params, status_code, duration_ms, client_host
        FROM api_request_log {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)
    return {"data": [dict(r._mapping) for r in rows], "total": total, "page": page, "limit": limit}


@router.get("/stats")
async def admin_stats(db: Db) -> dict[str, Any]:
    chat_agg = (await db.execute(text("""
        SELECT count(*)                                                       AS total_chats,
               coalesce(sum(input_tokens), 0)                                 AS total_input_tokens,
               coalesce(sum(output_tokens), 0)                                AS total_output_tokens,
               coalesce(round(avg(duration_ms))::int, 0)                      AS avg_duration_ms,
               coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::int, 0) AS p95_duration_ms,
               coalesce(sum(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0) AS error_count
        FROM chat_traces
    """))).fetchone()
    tool_freq = await db.execute(text("""
        SELECT tool_name, count(*) AS count, coalesce(round(avg(duration_ms))::int, 0) AS avg_duration_ms
        FROM tool_call_traces
        GROUP BY tool_name
        ORDER BY count DESC
    """))
    req_by_path = await db.execute(text("""
        SELECT path, count(*) AS count, coalesce(round(avg(duration_ms))::int, 0) AS avg_duration_ms
        FROM api_request_log
        GROUP BY path
        ORDER BY count DESC
        LIMIT 20
    """))
    return {
        "chats": dict(chat_agg._mapping),
        "tool_frequency": [dict(r._mapping) for r in tool_freq],
        "requests_by_path": [dict(r._mapping) for r in req_by_path],
    }
