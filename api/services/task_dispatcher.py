"""
Task Dispatcher
================
Dispatches build requests to Celery for async processing.
Uses send_task() to avoid importing worker modules directly.
"""
import logging
import uuid
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from core.models import BuildHistory

logger = logging.getLogger(__name__)

# Celery client (no need to import worker tasks)
celery_app = Celery(
    "agent_builder",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


async def dispatch_build_task(
    query: str,
    preferred_model: str | None,
    max_mcps: int,
    enable_skill_creation: bool,
    db: AsyncSession,
) -> str:
    """
    Create a build_history record and dispatch the task to Celery.
    Uses send_task() so we don't need worker code in the API container.

    Returns the Celery task_id.
    """
    # Generate task ID upfront
    task_id = str(uuid.uuid4())

    # Send task by name to the "build" queue (worker listens on "build")
    celery_app.send_task(
        "worker.tasks.build_agent.run_build_pipeline",
        kwargs={
            "query": query,
            "preferred_model": preferred_model,
            "max_mcps": max_mcps,
            "enable_skill_creation": enable_skill_creation,
        },
        task_id=task_id,
        queue="build",
    )

    # Record in database
    await db.execute(
        insert(BuildHistory).values(
            task_id=task_id,
            user_query=query,
            status="queued",
            current_node=None,
            processing_log=[{
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node": "dispatcher",
                "message": "Build request queued",
                "data": {
                    "preferred_model": preferred_model,
                    "max_mcps": max_mcps,
                    "enable_skill_creation": enable_skill_creation,
                },
            }],
        )
    )
    await db.commit()

    logger.info(f"Dispatched build task: {task_id}")
    return task_id
