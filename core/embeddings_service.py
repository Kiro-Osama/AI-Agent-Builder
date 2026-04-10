"""
Embedding catalog maintenance (MCPs + skills) — shared by API and CLI.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.embeddings import embedding_generator
from core.models import MCP, Skill

logger = logging.getLogger(__name__)


async def get_embedding_catalog_status(db: AsyncSession) -> dict[str, Any]:
    """Snapshot of embedding coverage for active MCPs and all skills."""
    gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())

    m_res = await db.execute(select(MCP).where(MCP.is_active == True).order_by(MCP.mcp_name))
    mcps = list(m_res.scalars().all())
    mcp_items = [{"mcp_name": m.mcp_name, "has_embedding": m.embedding is not None} for m in mcps]
    m_with = sum(1 for i in mcp_items if i["has_embedding"])
    m_total = len(mcp_items)

    s_res = await db.execute(select(Skill).order_by(Skill.skill_id))
    skills = list(s_res.scalars().all())
    skill_items = [
        {
            "skill_id": s.skill_id,
            "status": s.status,
            "has_embedding": s.embedding is not None,
            "has_description": bool((s.description or "").strip()),
        }
        for s in skills
    ]
    # Skills need a description to embed
    s_embeddable = [i for i in skill_items if i["has_description"]]
    s_with = sum(1 for i in s_embeddable if i["has_embedding"])
    s_total = len(s_embeddable)

    mcps_complete = m_total == 0 or (m_with == m_total)
    skills_complete = s_total == 0 or (s_with == s_total)

    return {
        "gemini_api_configured": gemini_configured,
        "mcps": {
            "total_active": m_total,
            "with_embedding": m_with,
            "without_embedding": m_total - m_with,
            "complete": mcps_complete,
            "items": mcp_items,
        },
        "skills": {
            "total_with_description": s_total,
            "with_embedding": s_with,
            "without_embedding": s_total - s_with,
            "complete": skills_complete,
            "items": skill_items,
        },
        "catalog_complete": mcps_complete and skills_complete,
    }


async def run_catalog_embeddings(
    db: AsyncSession,
    *,
    only_missing: bool = True,
    include_mcps: bool = True,
    include_skills: bool = True,
) -> dict[str, Any]:
    """
    Generate Gemini embeddings and store pgvector columns.
    Commits once at the end if no unhandled error.
    """
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise ValueError("GEMINI_API_KEY is not set")

    embedded_mcps = 0
    embedded_skills = 0
    errors: list[dict[str, str]] = []

    if include_mcps:
        q = select(MCP).where(MCP.is_active == True)
        if only_missing:
            q = q.where(MCP.embedding.is_(None))
        m_res = await db.execute(q.order_by(MCP.mcp_name))
        for m in m_res.scalars().all():
            try:
                vec = await embedding_generator.generate(m.description)
                vec_str = "[" + ",".join(str(x) for x in vec) + "]"
                await db.execute(
                    text("UPDATE mcps SET embedding = CAST(:vec AS vector) WHERE id = :id"),
                    {"vec": vec_str, "id": m.id},
                )
                embedded_mcps += 1
            except Exception as e:
                logger.exception("MCP embed failed: %s", m.mcp_name)
                errors.append({"target": "mcp", "id": m.mcp_name, "error": str(e)})

    if include_skills:
        q = select(Skill).where(Skill.description.isnot(None))
        if only_missing:
            q = q.where(Skill.embedding.is_(None))
        s_res = await db.execute(q.order_by(Skill.skill_id))
        for s in s_res.scalars().all():
            desc = (s.description or "").strip()
            if not desc:
                continue
            try:
                vec = await embedding_generator.generate(desc)
                vec_str = "[" + ",".join(str(x) for x in vec) + "]"
                await db.execute(
                    text("UPDATE skills SET embedding = CAST(:vec AS vector) WHERE id = :id"),
                    {"vec": vec_str, "id": s.id},
                )
                embedded_skills += 1
            except Exception as e:
                logger.exception("Skill embed failed: %s", s.skill_id)
                errors.append({"target": "skill", "id": s.skill_id, "error": str(e)})

    await db.commit()

    return {
        "embedded_mcps": embedded_mcps,
        "embedded_skills": embedded_skills,
        "errors": errors,
        "only_missing": only_missing,
    }
