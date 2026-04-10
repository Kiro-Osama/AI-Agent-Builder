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


def _extract_node_details(node_name: str, node_state: dict, accumulated: dict) -> dict:
    """Extract human-readable details from a node's output for the progress log."""
    details = {}

    if node_name == "query_analyzer":
        sq = node_state.get("sub_queries", [])
        details = {
            "summary": f"Generated {len(sq)} search queries",
            "sub_queries": sq[:6],
        }

    elif node_name == "similarity_retriever":
        mcps = node_state.get("retrieved_mcps", [])
        skills = node_state.get("retrieved_skills", [])
        details = {
            "summary": f"Found {len(mcps)} MCPs and {len(skills)} skills",
            "mcps_found": [
                {"name": m.get("mcp_name", "?"), "similarity": round(m.get("similarity", 0), 3)}
                for m in mcps[:8]
            ],
            "skills_found": [
                {"id": s.get("skill_id", "?"), "name": s.get("skill_name", "?"),
                 "similarity": round(s.get("similarity", 0), 3)}
                for s in sorted(skills, key=lambda x: x.get("similarity", 0), reverse=True)[:8]
            ],
        }

    elif node_name == "needs_assessment":
        action = node_state.get("needs_action", "proceed")
        missing = node_state.get("missing_capabilities", [])
        details = {
            "summary": "Creating new skill" if action == "create_skill" else "Existing tools sufficient",
            "action": action,
            "missing_capabilities": missing,
        }

    elif node_name == "skill_creator":
        new_skills = node_state.get("new_skills", [])
        details = {
            "summary": f"Created {len(new_skills)} new skill(s)" if new_skills else "No new skills needed",
            "created_skills": [
                {"id": s.get("skill_id", "?"), "name": s.get("skill_name", "?"),
                 "description": (s.get("description") or "")[:150]}
                for s in new_skills
            ],
        }

    elif node_name == "sandbox_validator":
        validated = node_state.get("validated_skills", [])
        details = {
            "summary": f"{len(validated)} skills validated and ready",
            "validated_count": len(validated),
        }

    elif node_name == "ai_final_filter":
        tools = node_state.get("selected_tools", {})
        sel_mcps = tools.get("mcps", [])
        sel_skills = tools.get("skills", [])
        details = {
            "summary": f"Selected {len(sel_mcps)} MCPs and {len(sel_skills)} skills",
            "selected_mcps": [m.get("mcp_name", "?") for m in sel_mcps],
            "selected_skills": [s.get("skill_id", "?") for s in sel_skills],
        }

    elif node_name == "docker_mcp_runner":
        running = node_state.get("running_mcps", [])
        details = {
            "summary": f"{len(running)} MCP container(s) prepared",
            "mcps": [
                {"name": m.get("mcp_name", "?"), "image": m.get("docker_image", "?"),
                 "status": m.get("status", "ready")}
                for m in running
            ],
        }

    elif node_name == "template_builder":
        tmpl = node_state.get("final_template", {})
        agent = tmpl.get("agents", [{}])[0] if tmpl.get("agents") else {}
        details = {
            "summary": f"Agent '{agent.get('agent_name', '?')}' configured" if agent else "No agent configured",
            "agent_name": agent.get("agent_name", "?"),
            "model": agent.get("assigned_openrouter_model", "?"),
            "mcps_count": len(agent.get("selected_mcps", [])),
            "skills_count": len(agent.get("selected_skills", [])),
            "has_warning": bool(tmpl.get("warning")),
        }

    elif node_name == "final_output":
        errors = node_state.get("errors") or accumulated.get("errors", [])
        details = {
            "summary": "Pipeline complete" + (f" with {len(errors)} warning(s)" if errors else ""),
            "total_errors": len(errors) if errors else 0,
        }

    return details


async def _run_graph_async(graph, initial_state: dict, task_id: str) -> dict:
    """Run the LangGraph pipeline asynchronously with detailed progress."""
    accumulated_state = dict(initial_state)
    final_state = None

    async for state in graph.astream(initial_state):
        for node_name, node_state in state.items():
            logger.info("  Node completed: %s", node_name)

            if isinstance(node_state, dict):
                accumulated_state.update(node_state)

            details = _extract_node_details(node_name, node_state if isinstance(node_state, dict) else {}, accumulated_state)

            update_build_status(
                task_id=task_id,
                status="processing",
                current_node=node_name,
                log_entry={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "node": node_name,
                    "message": details.get("summary", f"Node '{node_name}' completed"),
                    "details": details,
                },
            )
            final_state = node_state

    return final_state or initial_state
