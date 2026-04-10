"""
Manual Build Router
====================
POST /api/v1/build/manual - Create an agent directly without the LangGraph pipeline.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import BuildHistory, MCP, Skill

logger = logging.getLogger(__name__)
router = APIRouter()


class ManualBuildRequest(BaseModel):
    agent_name: str = Field("Custom_Agent", min_length=1, max_length=200)
    system_prompt: str = Field(
        "You are a helpful AI assistant. Use your tools when needed.",
        min_length=5,
    )
    selected_mcp_ids: list[int] = Field(default_factory=list)
    selected_skill_ids: list[str] = Field(default_factory=list)
    model: str = Field("google/gemma-3-27b-it:free")


@router.post("/build/manual")
async def manual_build(
    body: ManualBuildRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Build an agent directly by selecting MCPs, skills, and system prompt.
    Bypasses the LangGraph pipeline entirely.
    """
    if not body.selected_mcp_ids and not body.selected_skill_ids:
        raise HTTPException(400, "Select at least one MCP or skill")

    mcps_result = await db.execute(
        select(MCP).where(MCP.id.in_(body.selected_mcp_ids), MCP.is_active == True)
    )
    mcps = mcps_result.scalars().all()

    selected_mcps = []
    for m in mcps:
        selected_mcps.append({
            "mcp_name": m.mcp_name,
            "docker_image": m.docker_image,
            "run_config": m.run_config or {},
            "tools_provided": m.tools_provided or [],
            "requires_user_config": m.requires_user_config or False,
            "config_schema": m.config_schema or [],
        })

    skills_result = await db.execute(
        select(Skill).where(Skill.skill_id.in_(body.selected_skill_ids))
    )
    skills = skills_result.scalars().all()

    selected_skills = []
    for s in skills:
        selected_skills.append({
            "skill_id": s.skill_id,
            "skill_name": s.skill_name,
            "description": s.description or "",
            "system_prompt": s.system_prompt or "",
        })

    system_prompt = body.system_prompt
    if selected_skills:
        skill_section = "\n\n## Available Skills\n"
        for sk in selected_skills:
            if sk.get("system_prompt"):
                skill_section += f"\n### {sk['skill_name']}\n{sk['system_prompt']}\n"
        system_prompt = system_prompt + skill_section

    template = {
        "project_type": "single_agent",
        "agents": [
            {
                "agent_name": body.agent_name,
                "system_prompt": system_prompt,
                "assigned_openrouter_model": body.model,
                "selected_mcps": selected_mcps,
                "selected_skills": selected_skills,
            }
        ],
    }

    task_id = f"manual-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    build = BuildHistory(
        task_id=task_id,
        user_query=f"[Manual Build] {body.agent_name}",
        status="completed",
        current_node="manual",
        result_template=template,
        selected_mcps=[m.to_dict() for m in mcps],
        selected_skills=[s.to_dict() for s in skills],
        processing_log=[{
            "node": "manual",
            "status": "completed",
            "details": {"summary": "Agent built manually by user"},
        }],
        started_at=now,
        completed_at=now,
    )
    db.add(build)
    await db.commit()

    logger.info(f"Manual build created: {task_id} ({body.agent_name})")

    return {
        "task_id": task_id,
        "status": "completed",
        "agent_name": body.agent_name,
        "mcps_count": len(selected_mcps),
        "skills_count": len(selected_skills),
        "template": template,
    }
