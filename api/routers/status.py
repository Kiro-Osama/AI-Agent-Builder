"""
Status Router
==============
GET /api/v1/status/{task_id} - Poll pipeline progress.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import StatusResponse
from core.db import get_db
from core.models import BuildHistory

logger = logging.getLogger(__name__)
router = APIRouter()

# Node weights for progress calculation
NODE_PROGRESS = {
    "query_analyzer": 0.10,
    "similarity_retriever": 0.20,
    "needs_assessment": 0.30,
    "skill_creator": 0.40,
    "sandbox_validator": 0.50,
    "ai_final_filter": 0.65,
    "docker_mcp_runner": 0.80,
    "template_builder": 0.90,
    "final_output": 1.0,
}


@router.get("/status/{task_id}", response_model=StatusResponse)
async def get_build_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current status of a build pipeline.

    Returns the current node, progress percentage, logs,
    and the final template when completed.
    """
    result = await db.execute(
        select(BuildHistory).where(BuildHistory.task_id == task_id)
    )
    build = result.scalar_one_or_none()

    if not build:
        raise HTTPException(status_code=404, detail=f"Build {task_id} not found")

    # Calculate progress
    progress = NODE_PROGRESS.get(build.current_node, 0.0)
    if build.status == "completed":
        progress = 1.0
    elif build.status == "failed":
        progress = progress  # Keep last known progress

    return StatusResponse(
        task_id=build.task_id,
        status=build.status,
        current_node=build.current_node,
        progress=progress,
        processing_log=build.processing_log or [],
        result_template=build.result_template,
        error=None if build.status != "failed" else "Pipeline failed. Check processing_log for details.",
    )
