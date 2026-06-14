"""
Chat endpoint — SSE streaming with Claude tool-use loop.

POST /api/chat  body: {"messages": [...], "stream": true}
Returns: text/event-stream

Event types:
  data: {"type": "text",       "content": "..."}
  data: {"type": "tool_call",  "name": "...", "input": {...}}
  data: {"type": "tool_result","name": "...", "result": {...}}
  data: {"type": "done"}
  data: {"type": "error",      "message": "..."}
"""

import json
import sys
import time
from typing import Annotated, Any, AsyncGenerator

import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.system_prompt import SYSTEM_PROMPT
from app.chat.tools import TOOLS
from app.chat.tracing import TraceRecorder
from app.config import ANTHROPIC_API_KEY, CHAT_MODEL
from app.db import get_db
from app.retrieval.hybrid import search_emails, search_key_points, search_trade_ideas

router = APIRouter(tags=["chat"])

Db = Annotated[AsyncSession, Depends(get_db)]
_claude = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

MAX_TOOL_ROUNDS = 5  # prevent infinite loops


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]


@router.post("/chat")
async def chat(req: ChatRequest, db: Db):
    return StreamingResponse(
        _stream(req.messages, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(messages: list[dict], db: AsyncSession) -> AsyncGenerator[str, None]:
    recorder = TraceRecorder(model=CHAT_MODEL, request_messages=messages)
    try:
        async for event in _tool_loop(messages, db, recorder):
            yield f"data: {json.dumps(event, default=str)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as exc:
        recorder.fail(str(exc))
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
    finally:
        # Best-effort: a trace-write failure must never break the user response.
        try:
            await recorder.persist()
        except Exception as exc:
            print(f"[trace] failed to persist chat trace: {exc}", file=sys.stderr)


async def _tool_loop(
    messages: list[dict], db: AsyncSession, recorder: TraceRecorder
) -> AsyncGenerator[dict, None]:
    history = list(messages)
    last_text = ""

    for _round in range(MAX_TOOL_ROUNDS):
        # Stream Claude's response
        text_so_far = ""
        tool_calls: list[dict] = []

        async with _claude.messages.stream(
            model=CHAT_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        ) as stream:
            async for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "text"):
                            text_so_far += delta.text
                            yield {"type": "text", "content": delta.text}
                        elif hasattr(delta, "partial_json"):
                            # accumulate tool input JSON — handled at block_stop
                            pass
                    elif event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "name": block.name,
                                "input_json": "",
                            })
                    elif event.type == "content_block_stop":
                        pass

            # Get the final message after streaming completes
            final = await stream.get_final_message()

        # Check stop reason
        stop_reason = final.stop_reason
        recorder.add_round(final.usage, stop_reason)
        last_text = text_so_far

        # Add assistant turn to history
        history.append({"role": "assistant", "content": final.content})

        if stop_reason == "end_turn" or not tool_calls:
            recorder.finish(last_text, "ok")
            return

        if stop_reason == "tool_use":
            # Extract tool calls from final.content
            tool_results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                yield {"type": "tool_call", "name": tool_name, "input": tool_input}

                t0 = time.perf_counter()
                result = await _dispatch_tool(tool_name, tool_input, db)
                duration_ms = int((time.perf_counter() - t0) * 1000)
                recorder.add_tool(_round, tool_name, tool_input, result, duration_ms)
                yield {"type": "tool_result", "name": tool_name, "result": result}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })

            history.append({"role": "user", "content": tool_results})

        else:
            recorder.finish(last_text, "ok")
            return

    # Loop exhausted without returning → hit the round cap mid tool-use.
    recorder.finish(last_text, "max_rounds")


async def _dispatch_tool(name: str, input_: dict, db: AsyncSession) -> Any:
    if name == "search_key_points":
        results = await search_key_points(db, **_coerce(input_, "query"))
        return [vars(r) for r in results]

    if name == "search_trade_ideas":
        results = await search_trade_ideas(db, **_coerce(input_, "query"))
        return [vars(r) for r in results]

    if name == "search_emails":
        results = await search_emails(db, **_coerce(input_, "query"))
        return [
            {
                "email_content_hash": r.email_content_hash,
                "email_subject": r.email_subject,
                "email_from": r.email_from,
                "email_sent_dt": str(r.email_sent_dt),
                "matched_chunk": r.matched_chunk,
                "related_key_points": [vars(kp) for kp in r.related_key_points],
                "related_trade_ideas": [vars(ti) for ti in r.related_trade_ideas],
            }
            for r in results
        ]

    if name == "get_disagreements":
        return await _get_disagreements(db, input_)

    if name == "get_topic_summary":
        return await _get_topic_summary(db, input_)

    if name == "get_stats":
        return await _get_stats(db, input_)

    return {"error": f"Unknown tool: {name}"}


def _coerce(input_: dict, required_key: str) -> dict:
    """Pass tool input directly as kwargs, ensuring required key exists."""
    out = dict(input_)
    # Rename top_k if present (Claude may send it as-is)
    return out


# ── SQL tool implementations ───────────────────────────────────────────────────

async def _get_disagreements(db: AsyncSession, input_: dict) -> list[dict]:
    filters: list[str] = ["dv.is_false_positive = false"]
    params: dict[str, Any] = {"limit": input_.get("limit", 10)}

    if input_.get("topics"):
        filters.append("d.group_key = ANY(:topics)")
        params["topics"] = input_["topics"]
    if input_.get("geographies"):
        filters.append("d.geography = ANY(:geos)")
        params["geos"] = input_["geographies"]
    if input_.get("scale"):
        filters.append("d.scale = ANY(:scale)")
        params["scale"] = input_["scale"]
    if input_.get("date_from"):
        filters.append("d.window_end >= :date_from")
        params["date_from"] = input_["date_from"]
    if input_.get("date_to"):
        filters.append("d.window_start <= :date_to")
        params["date_to"] = input_["date_to"]

    where = "WHERE " + " AND ".join(filters)
    sql = text(f"""
        SELECT d.disagreement_id, d.group_key, d.geography, d.window_start, d.window_end,
               d.scale, d.n_banks, d.sentiment_spread, d.bank_positions,
               dv.resolution_summary, dv.status, dv.bank_analysis
        FROM disagreements d
        JOIN disagreement_validations dv ON dv.disagreement_id = d.disagreement_id
        {where}
        ORDER BY d.window_end DESC, d.scale DESC
        LIMIT :limit
    """)
    rows = await db.execute(sql, params)
    cols = ["disagreement_id", "group_key", "geography", "window_start", "window_end",
            "scale", "n_banks", "sentiment_spread", "bank_positions",
            "resolution_summary", "status", "bank_analysis"]
    return [dict(zip(cols, r)) for r in rows]


async def _get_topic_summary(db: AsyncSession, input_: dict) -> list[dict]:
    filters: list[str] = []
    params: dict[str, Any] = {"limit": input_.get("limit", 5)}

    if input_.get("topic"):
        filters.append("topic = :topic")
        params["topic"] = input_["topic"]
    if input_.get("date"):
        filters.append("window_start::date <= :date AND window_end::date >= :date")
        params["date"] = input_["date"]

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(f"""
        SELECT topic, window_start, window_end, bullets, bullet_count,
               source_orgs, kp_count, label_map
        FROM topic_summaries {where}
        ORDER BY window_end DESC LIMIT :limit
    """)
    rows = await db.execute(sql, params)
    cols = ["topic", "window_start", "window_end", "bullets", "bullet_count",
            "source_orgs", "kp_count", "label_map"]
    summaries = [dict(zip(cols, r)) for r in rows]

    # Batch-resolve label_map key_point_ids → citation metadata for the frontend
    all_kp_ids: list[str] = []
    for s in summaries:
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
        for s in summaries:
            lm = s.get("label_map") or {}
            s["label_map_enriched"] = {
                label: kp_meta[kp_id]
                for label, kp_id in lm.items()
                if kp_id in kp_meta
            }
    else:
        for s in summaries:
            s["label_map_enriched"] = {}

    return summaries


_STATS_QUERIES: dict[str, str] = {
    "count_by_bank": """
        SELECT effective_source_org AS bank, count(*) AS key_point_count
        FROM key_points_full {where}
        GROUP BY effective_source_org ORDER BY key_point_count DESC LIMIT 20
    """,
    "sentiment_distribution": """
        SELECT sentiment, count(*) AS count
        FROM key_points_full {where}
        GROUP BY sentiment ORDER BY count DESC
    """,
    "topic_frequency": """
        SELECT unnest(topics) AS topic, count(*) AS count
        FROM key_points_full {where}
        GROUP BY topic ORDER BY count DESC LIMIT 20
    """,
    "asset_class_breakdown": """
        SELECT asset_class, count(*) AS trade_count
        FROM trade_ideas_full {where}
        GROUP BY asset_class ORDER BY trade_count DESC
    """,
    "disagreement_by_topic": """
        SELECT d.group_key AS topic, count(*) AS disagreement_count
        FROM disagreements d
        JOIN disagreement_validations dv ON dv.disagreement_id = d.disagreement_id
        WHERE dv.is_false_positive = false {extra}
        GROUP BY d.group_key ORDER BY disagreement_count DESC LIMIT 20
    """,
}


async def _get_stats(db: AsyncSession, input_: dict) -> list[dict]:
    metric = input_["metric"]
    f = input_.get("filters", {}) or {}

    filters: list[str] = []
    params: dict[str, Any] = {}

    if f.get("source_org"):
        filters.append("effective_source_org = :source_org")
        params["source_org"] = f["source_org"]
    if f.get("topic") and metric != "topic_frequency":
        filters.append("topics @> ARRAY[:topic]::varchar[]")
        params["topic"] = f["topic"]
    if f.get("geography"):
        filters.append("geographies @> ARRAY[:geography]::varchar[]")
        params["geography"] = f["geography"]
    if f.get("sentiment"):
        filters.append("sentiment = :sentiment")
        params["sentiment"] = f["sentiment"]
    if f.get("date_from"):
        filters.append("email_sent_dt >= :date_from")
        params["date_from"] = f["date_from"]
    if f.get("date_to"):
        filters.append("email_sent_dt <= :date_to")
        params["date_to"] = f["date_to"]

    template = _STATS_QUERIES.get(metric, "")
    if not template:
        return [{"error": f"Unknown metric: {metric}"}]

    if metric == "disagreement_by_topic":
        extra = (" AND " + " AND ".join(filters)) if filters else ""
        sql = text(template.format(extra=extra))
    else:
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        sql = text(template.format(where=where))

    rows = await db.execute(sql, params)
    return [dict(r._mapping) for r in rows]
