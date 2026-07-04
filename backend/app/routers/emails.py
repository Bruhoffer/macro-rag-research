from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.retrieval.hybrid import search_emails
from app.utils.redact import redact_addresses

router = APIRouter(tags=["emails"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/search")
async def search_emails_endpoint(
    db: Db,
    q: str,
    source_org: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    results = await search_emails(
        db, q,
        source_orgs=source_org,
        date_from=date_from,
        date_to=date_to,
        top_k=limit,
    )
    return {"data": [_email_result_to_dict(r) for r in results]}


@router.get("/{email_hash}")
async def get_email(email_hash: str, db: Db) -> dict[str, Any]:
    row = await db.execute(text("""
        SELECT email_content_hash, email_subject, email_from,
               email_sent_dt, file_name, email_body
        FROM emails WHERE email_content_hash = :hash
    """), {"hash": email_hash})
    e = row.fetchone()
    if not e:
        raise HTTPException(status_code=404, detail="Email not found")

    kp_rows = await db.execute(text("""
        SELECT key_point_id, key_point_text, key_point_citation,
               effective_source_org, sentiment, topics
        FROM key_points_full WHERE email_content_hash = :hash
        ORDER BY email_sent_dt
    """), {"hash": email_hash})

    ti_rows = await db.execute(text("""
        SELECT trade_idea_id, trade_idea_text, trade_idea_citation,
               effective_source_org, asset_class
        FROM trade_ideas_full WHERE email_content_hash = :hash
        ORDER BY email_sent_dt
    """), {"hash": email_hash})

    # DB is scrubbed at ingestion (see scripts/scrub_pii.py); redact_addresses
    # here is defense-in-depth only.
    return {
        "email_content_hash": e[0],
        "email_subject": redact_addresses(e[1]) or "",
        "email_from": redact_addresses(e[2]) or "",
        "email_sent_dt": e[3],
        "file_name": e[4] or "",
        "email_body": redact_addresses(e[5]) or "",
        "related_key_points": [
            {
                "key_point_id": str(r[0]),
                "key_point_text": r[1] or "",
                "key_point_citation": r[2] or "",
                "effective_source_org": r[3] or "",
                "sentiment": r[4] or "",
                "topics": r[5] or [],
            }
            for r in kp_rows
        ],
        "related_trade_ideas": [
            {
                "trade_idea_id": str(r[0]),
                "trade_idea_text": r[1] or "",
                "trade_idea_citation": r[2] or "",
                "effective_source_org": r[3] or "",
                "asset_class": r[4] or "",
            }
            for r in ti_rows
        ],
    }


def _email_result_to_dict(r) -> dict[str, Any]:
    return {
        "email_content_hash": r.email_content_hash,
        "email_subject": redact_addresses(r.email_subject),
        "email_from": redact_addresses(r.email_from),
        "email_sent_dt": r.email_sent_dt,
        "file_name": r.file_name,
        "email_body": redact_addresses(r.email_body),
        "matched_chunk": redact_addresses(r.matched_chunk),
        "related_key_points": [vars(kp) for kp in r.related_key_points],
        "related_trade_ideas": [vars(ti) for ti in r.related_trade_ideas],
    }
