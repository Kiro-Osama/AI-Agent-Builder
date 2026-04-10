"""
Build Agent Task
=================
Main Celery task: runs the LangGraph pipeline end-to-end.
Updates build_history at each node for real-time status.
"""
import logging
from datetime import datetime, timezone

from worker.celery_app import app
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from core.models import BuildHistory

logger = logging.getLogger(__name__)

import os

_SYNC_DB_URL = os.getenv("ALEMBIC_DATABASE_URL", "").strip()
if not _SYNC_DB_URL:
    raise RuntimeError(
        "ALEMBIC_DATABASE_URL is required for the worker (sync URL, e.g. postgresql://user:pass@db:5432/dbname)."
    )


def get_sync_session() -> Session:
    """Create a sync database session for Celery tasks."""
    engine = create_engine(_SYNC_DB_URL)
    return Session(engine)


def update_build_status(
    task_id: str,
    status: str,
    current_node: str,
    log_entry: dict | None = None,
    result_template: dict | None = None,
    selected_mcps: list | None = None,
    selected_skills: list | None = None,
):
    """Update build_history record with current progress."""
    session = get_sync_session()
    try:
        values = {
            "status": status,
            "current_node": current_node,
        }

        if result_template:
            values["result_template"] = result_template
        if selected_mcps is not None:
            values["selected_mcps"] = selected_mcps
        if selected_skills is not None:
            values["selected_skills"] = selected_skills

        if status == "processing" and log_entry:
            # Append to processing_log
            build = session.query(BuildHistory).filter_by(task_id=task_id).first()
            if build:
                logs = build.processing_log or []
                logs.append(log_entry)
                values["processing_log"] = logs

        if status == "completed":
            values["completed_at"] = datetime.now(timezone.utc)

        session.execute(
            update(BuildHistory).where(BuildHistory.task_id == task_id).values(**values)
        )
        session.commit()
    except Exception as e:
        logger.error(f"Failed to update build status: {e}")
        session.rollback()
    finally:
        session.close()


@app.task(bind=True, name="worker.tasks.build_agent.run_build_pipeline")
def run_build_pipeline(
    self,
    query: str,
    preferred_model: str | None = None,
    max_mcps: int = 5,
    enable_skill_creation: bool = True,
):
    """
    Main pipeline task. Runs the LangGraph StateGraph.

    Args:
        query: User's task description
        preferred_model: Preferred OpenRouter model
        max_mcps: Maximum MCPs to select
        enable_skill_creation: Allow dynamic skill creation
    """
    import asyncio

    task_id = self.request.id
    logger.info(f"🏗️ Starting build pipeline: {task_id}")

    # Mark as processing
    update_build_status(
        task_id=task_id,
        status="processing",
        current_node="query_analyzer",
        log_entry={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": "pipeline",
            "message": "Pipeline started",
        },
    )

    try:
        # Import and run the LangGraph pipeline
        from orchestrator.graph import build_agent_graph

        graph = build_agent_graph()

        # Run async graph in sync context
        initial_state = {
            "user_query": query,
            "preferred_model": preferred_model,
            "max_mcps": max_mcps,
            "enable_skill_creation": enable_skill_creation,
            "sub_queries": [],
            "retrieved_mcps": [],
            "retrieved_skills": [],
            "missing_capabilities": [],
            "new_skills": [],
            "validated_skills": [],
            "selected_tools": {},
            "running_mcps": [],
            "final_template": {},
            "status": "processing",
            "errors": [],
            "task_id": task_id,
        }

        # Execute graph
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _run_graph_async(graph, initial_state, task_id)
            )
        finally:
            loop.close()

        # Update final result
        update_build_status(
            task_id=task_id,
            status="completed",
            current_node="final_output",
            result_template=result.get("final_template", {}),
            selected_mcps=result.get("running_mcps", []),
            selected_skills=[s.get("skill_id") for s in result.get("validated_skills", [])],
            log_entry={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node": "pipeline",
                "message": "Pipeline completed successfully",
            },
        )

        logger.info(f"✅ Build pipeline completed: {task_id}")
        return result.get("final_template", {})

    except Exception as e:
        logger.error(f"❌ Build pipeline failed: {task_id} - {e}")
        update_build_status(
            task_id=task_id,
            status="failed",
            current_node="error",
            log_entry={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node": "pipeline",
                "message": f"Pipeline failed: {str(e)}",
            },
        )
        raise


async def _run_graph_async(graph, initial_state: dict, task_id: str) -> dict:
    """Run the LangGraph pipeline asynchronously."""
    final_state = None
    async for state in graph.astream(initial_state):
        # state is a dict with the node name as key
        for node_name, node_state in state.items():
            logger.info(f"  Node completed: {node_name}")
            update_build_status(
                task_id=task_id,
                status="processing",
                current_node=node_name,
                log_entry={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "node": node_name,
                    "message": f"Node '{node_name}' completed",
                },
            )
            final_state = node_state

    return final_state or initial_state
