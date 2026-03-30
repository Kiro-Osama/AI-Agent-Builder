"""
Build Router
=============
POST /api/v1/build - Submit agent build requests to Celery.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import BuildRequest, BuildResponse
from api.services.task_dispatcher import dispatch_build_task
from core.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/build", response_model=BuildResponse)
async def build_agent(
    request: BuildRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a new agent build request.

    The request is dispatched to a Celery worker that runs the
    LangGraph pipeline (9 nodes) to build the agent template.
    """
    try:
        task_id = await dispatch_build_task(
            query=request.query,
            preferred_model=request.preferred_model,
            max_mcps=request.max_mcps,
            enable_skill_creation=request.enable_skill_creation,
            db=db,
        )

        logger.info(f"Build request submitted: task_id={task_id}")

        return BuildResponse(
            task_id=task_id,
            status="queued",
            message="Build request submitted. Use /api/v1/status/{task_id} to track progress.",
        )

    except Exception as e:
        logger.error(f"Build request failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit build: {str(e)}")
