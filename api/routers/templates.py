"""
Templates Router
=================
GET /api/v1/templates - List completed agent templates.
GET /api/v1/templates/{template_id} - Get a specific template.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import BuildHistory

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/templates")
async def list_templates(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all completed agent templates."""
    count_result = await db.execute(
        select(func.count()).select_from(BuildHistory).where(BuildHistory.status == "completed")
    )
    total_count = int(count_result.scalar_one() or 0)

    result = await db.execute(
        select(BuildHistory)
        .where(BuildHistory.status == "completed")
        .order_by(BuildHistory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    builds = result.scalars().all()

    return {
        "templates": [
            {
                "id": str(b.id),
                "task_id": b.task_id,
                "user_query": b.user_query,
                "status": b.status,
                "template": b.result_template,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in builds
        ],
        "total": total_count,
    }


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific agent template by build ID or task_id."""
    # Try by task_id first
    result = await db.execute(
        select(BuildHistory).where(BuildHistory.task_id == template_id)
    )
    build = result.scalar_one_or_none()

    if not build:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    return {
        "id": str(build.id),
        "task_id": build.task_id,
        "user_query": build.user_query,
        "status": build.status,
        "result_template": build.result_template,
        "selected_mcps": build.selected_mcps,
        "selected_skills": build.selected_skills,
        "processing_log": build.processing_log,
        "created_at": build.created_at.isoformat() if build.created_at else None,
        "completed_at": build.completed_at.isoformat() if build.completed_at else None,
    }


@router.get("/mcps")
async def list_mcps(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all available MCPs (static tools)."""
    from core.models import MCP

    query = select(MCP).where(MCP.is_active == True)
    if category:
        query = query.where(MCP.category == category)

    result = await db.execute(query)
    mcps = result.scalars().all()

    categories = sorted({m.category for m in mcps if m.category})
    return {
        "mcps": [m.to_dict() for m in mcps],
        "total": len(mcps),
        "categories": categories,
    }


@router.get("/skills")
async def list_skills(
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all skills (dynamic capabilities)."""
    from core.models import Skill

    query = select(Skill)
    if status_filter:
        query = query.where(Skill.status == status_filter)
    query = query.order_by(Skill.created_at.desc())

    result = await db.execute(query)
    skills = result.scalars().all()

    return {
        "skills": [s.to_dict() for s in skills],
        "total": len(skills),
        "categories": list({s.category for s in skills if s.category}),
    }
