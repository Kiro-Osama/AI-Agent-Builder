"""
Dashboard Router
=================
GET /api/v1/dashboard - Lists all previous agents and workflows.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import BuildHistory, Workflow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard")


@router.get("")
async def get_dashboard(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a unified dashboard showing all previous agent builds and workflows.
    Returns both lists sorted by most recent first.
    """
    # --- Fetch agent builds ---
    builds_query = (
        select(BuildHistory)
        .order_by(desc(BuildHistory.created_at))
        .limit(limit)
    )
    builds_result = await db.execute(builds_query)
    builds = builds_result.scalars().all()

    agent_items = []
    for b in builds:
        tmpl = b.result_template or {}
        agents_list = tmpl.get("agents", [])
        agent_name = agents_list[0].get("agent_name", "Unknown") if agents_list else "Unknown"
        model = agents_list[0].get("assigned_openrouter_model", "") if agents_list else ""
        mcps_count = len(agents_list[0].get("selected_mcps", [])) if agents_list else 0
        skills_count = len(agents_list[0].get("selected_skills", [])) if agents_list else 0

        agent_items.append({
            "type": "agent",
            "task_id": b.task_id,
            "name": agent_name,
            "query": b.user_query,
            "status": b.status,
            "model": model,
            "mcps_count": mcps_count,
            "skills_count": skills_count,
            "current_node": b.current_node,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        })

    # --- Fetch workflows ---
    wf_query = (
        select(Workflow)
        .order_by(desc(Workflow.created_at))
        .limit(limit)
    )
    wf_result = await db.execute(wf_query)
    workflows = wf_result.scalars().all()

    workflow_items = []
    for wf in workflows:
        agents_data = wf.agents or []
        memory_cfg = wf.memory_config or {}

        workflow_items.append({
            "type": "workflow",
            "workflow_id": wf.workflow_id,
            "name": wf.name or "Untitled Workflow",
            "description": wf.description,
            "query": wf.user_query,
            "topology": wf.topology,
            "status": wf.status,
            "agents_count": len(agents_data),
            "agent_names": [a.get("agent_name", "?") for a in agents_data if isinstance(a, dict)],
            "memory_config": memory_cfg,
            "memory_type": memory_cfg.get("memory_type", "shared") if memory_cfg else "shared",
            "memory_backend": memory_cfg.get("backend", "conversation") if memory_cfg else "conversation",
            "error_log": wf.error_log,
            "created_at": wf.created_at.isoformat() if wf.created_at else None,
            "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
        })

    # --- Counts ---
    agent_count = await db.execute(select(func.count()).select_from(BuildHistory))
    wf_count = await db.execute(select(func.count()).select_from(Workflow))

    return {
        "agents": agent_items,
        "workflows": workflow_items,
        "totals": {
            "agents": agent_count.scalar() or 0,
            "workflows": wf_count.scalar() or 0,
        },
    }
