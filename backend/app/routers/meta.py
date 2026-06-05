from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["meta"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/source-orgs")
async def list_source_orgs(db: Db) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT org_shortform_name, org_name, org_aliases FROM source_orgs ORDER BY org_shortform_name"
    ))
    return [{"shortform": r[0], "name": r[1], "aliases": r[2] or []} for r in rows]


@router.get("/topics")
async def list_topics(db: Db) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT topic_name, description FROM topics WHERE is_active = true ORDER BY topic_name"
    ))
    return [{"name": r[0], "description": r[1]} for r in rows]


@router.get("/geographies")
async def list_geographies(db: Db) -> list[dict[str, Any]]:
    rows = await db.execute(text(
        "SELECT geography_name, description FROM geographies WHERE is_active = true ORDER BY geography_name"
    ))
    return [{"name": r[0], "description": r[1]} for r in rows]
