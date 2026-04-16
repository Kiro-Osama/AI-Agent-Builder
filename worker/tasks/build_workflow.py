"""
Build Workflow Task
====================
Celery task that:
1. Runs the Workflow Planner to decompose the user query.
2. Dispatches individual agent builds via the existing single-agent pipeline.
3. Polls for completion of each sub-build.
4. Assembles the final workflow template and stores it.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from worker.celery_app import app
from sqlalchemy import create_engine, update, insert, select, text
from sqlalchemy.orm import Session

from core.models import Workflow, BuildHistory
from core.workflow_topologies import (
    TopologyType,
    get_supervisor_system_prompt,
)

logger = logging.getLogger(__name__)

_SYNC_DB_URL = os.getenv("ALEMBIC_DATABASE_URL", "").strip()
if not _SYNC_DB_URL:
    raise RuntimeError("ALEMBIC_DATABASE_URL is required for the worker.")

_engine = create_engine(_SYNC_DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)

POLL_INTERVAL = 5
MAX_POLL_TIME = 600


def _get_session() -> Session:
    return Session(_engine)


def _update_workflow(workflow_id: str, **values):
    """Update a workflow row by workflow_id."""
    sess = _get_session()
    try:
        sess.execute(
            update(Workflow).where(Workflow.workflow_id == workflow_id).values(**values)
        )
        sess.commit()
    except Exception as e:
        logger.error("Failed to update workflow %s: %s", workflow_id, e)
        sess.rollback()
    finally:
        sess.close()


def _dispatch_single_agent_build(
    query: str,
    preferred_model: str | None = None,
    max_mcps: int = 5,
    enable_skill_creation: bool = True,
    llm_provider: str | None = None,
) -> str:
    """Dispatch a single-agent build via Celery send_task, return task_id."""
    task_id = str(uuid.uuid4())

    sess = _get_session()
    try:
        sess.execute(
            insert(BuildHistory).values(
                task_id=task_id,
                user_query=query,
                status="queued",
                current_node=None,
                processing_log=[{
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "node": "workflow_dispatcher",
                    "message": "Sub-agent build queued by workflow planner",
                }],
            )
        )
        sess.commit()
    finally:
        sess.close()

    app.send_task(
        "worker.tasks.build_agent.run_build_pipeline",
        kwargs={
            "query": query,
            "preferred_model": preferred_model,
            "max_mcps": max_mcps,
            "enable_skill_creation": enable_skill_creation,
            "llm_provider": llm_provider,
        },
        task_id=task_id,
        queue="build",
    )

    logger.info("[BuildWorkflow] Dispatched sub-build %s for: %s", task_id, query[:80])
    return task_id


def _poll_build_completion(task_ids: list[str]) -> dict[str, dict]:
    """Poll build_history until all tasks complete or timeout."""
    results: dict[str, dict] = {}
    remaining = set(task_ids)
    start = time.time()

    while remaining and (time.time() - start) < MAX_POLL_TIME:
        time.sleep(POLL_INTERVAL)
        sess = _get_session()
        try:
            rows = sess.execute(
                select(
                    BuildHistory.task_id,
                    BuildHistory.status,
                    BuildHistory.result_template,
                ).where(BuildHistory.task_id.in_(list(remaining)))
            ).fetchall()

            for row in rows:
                tid, status, tmpl = row
                if status in ("completed", "failed"):
                    results[tid] = {
                        "status": status,
                        "result_template": tmpl,
                    }
                    remaining.discard(tid)
                    logger.info("[BuildWorkflow] Sub-build %s → %s", tid, status)
        finally:
            sess.close()

    for tid in remaining:
        results[tid] = {"status": "timeout", "result_template": None}
        logger.warning("[BuildWorkflow] Sub-build %s timed out", tid)

    return results


@app.task(bind=True, name="worker.tasks.build_workflow.run_workflow_build")
def run_workflow_build(
    self,
    user_query: str,
    workflow_id: str,
    topology_hint: str | None = None,
    preferred_model: str | None = None,
    llm_provider: str | None = None,
):
    """
    Main workflow build task.

    1. Call the LLM planner to decompose the task.
    2. Dispatch sub-agent builds.
    3. Collect results, assemble workflow template.
    """
    logger.info("[BuildWorkflow] Starting workflow build: %s", workflow_id)

    _update_workflow(workflow_id, status="planning")

    # --- Step 1: Plan the workflow ---
    from core.ollama_client import use_llm_provider

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from orchestrator.workflow_planner import plan_workflow

        with use_llm_provider(llm_provider):
            plan = loop.run_until_complete(plan_workflow(user_query, topology_hint))
    except Exception as e:
        logger.error("[BuildWorkflow] Planning failed: %s", e)
        _update_workflow(
            workflow_id,
            status="failed",
            error_log=f"Planning failed: {e}",
        )
        raise
    finally:
        loop.close()

    _update_workflow(
        workflow_id,
        status="building",
        name=plan.workflow_name,
        description=plan.reasoning,
        topology=plan.topology.value,
        agents=plan.to_dict()["agents"],
        workflow_config=plan.routing_rules,
        shared_state_schema=plan.shared_state_schema,
    )

    # --- Step 2: Dispatch individual agent builds ---
    task_id_to_role: dict[str, str] = {}
    build_task_ids: list[str] = []

    for agent_role in plan.agents:
        build_query = (
            f"Build a focused agent for this specific role:\n"
            f"Role: {agent_role.role}\n"
            f"Task: {agent_role.sub_task}\n"
        )
        if agent_role.needs_mcps:
            build_query += f"Preferred MCPs/capabilities: {', '.join(agent_role.needs_mcps)}\n"
        if agent_role.needs_skills:
            build_query += f"Preferred skills: {', '.join(agent_role.needs_skills)}\n"

        tid = _dispatch_single_agent_build(
            query=build_query,
            preferred_model=preferred_model,
            max_mcps=3,
            enable_skill_creation=True,
            llm_provider=llm_provider,
        )
        task_id_to_role[tid] = agent_role.role
        agent_role.task_id = tid
        build_task_ids.append(tid)

    _update_workflow(workflow_id, build_task_ids=build_task_ids)

    # --- Step 3: Poll for all builds to complete ---
    logger.info(
        "[BuildWorkflow] Waiting for %d sub-builds to complete...",
        len(build_task_ids),
    )
    build_results = _poll_build_completion(build_task_ids)

    # --- Step 4: Assemble workflow template ---
    failed_agents: list[str] = []
    assembled_agents: list[dict] = []

    for agent_role in plan.agents:
        tid = agent_role.task_id
        result = build_results.get(tid, {})
        status = result.get("status", "unknown")
        tmpl = result.get("result_template") or {}

        if status != "completed" or not tmpl:
            failed_agents.append(f"{agent_role.role} ({tid}): {status}")
            continue

        built_agent = tmpl.get("agents", [{}])[0] if tmpl.get("agents") else {}

        agent_entry = {
            "role": agent_role.role,
            "task_id": tid,
            "agent_name": built_agent.get("agent_name", agent_role.agent_name),
            "model": built_agent.get("assigned_openrouter_model", ""),
            "system_prompt": built_agent.get("system_prompt", ""),
            "selected_mcps": built_agent.get("selected_mcps", []),
            "selected_skills": built_agent.get("selected_skills", []),
            "sub_task": agent_role.sub_task,
            "accepts_from": agent_role.accepts_from,
            "reports_to": agent_role.reports_to,
            "reads_from_shared_state": agent_role.reads_from_shared_state,
            "output_to_shared_state": agent_role.output_to_shared_state,
        }

        # For supervisor topology: inject supervisor system prompt
        if (
            plan.topology == TopologyType.SUPERVISOR
            and agent_role.role == (plan.supervisor_config or {}).get("supervisor_role", plan.agents[0].role)
        ):
            workers = [a for a in plan.agents if a.role != agent_role.role]
            agent_entry["system_prompt"] = get_supervisor_system_prompt(
                supervisor_name=agent_entry["agent_name"],
                workers=workers,
                workflow_name=plan.workflow_name,
            )

        assembled_agents.append(agent_entry)

    if failed_agents:
        error_summary = "; ".join(failed_agents)
        logger.warning("[BuildWorkflow] Some agents failed: %s", error_summary)

    # Build the final workflow config
    supervisor_entry = None
    if plan.topology == TopologyType.SUPERVISOR:
        sup_role = (plan.supervisor_config or {}).get("supervisor_role", plan.agents[0].role)
        for a in assembled_agents:
            if a["role"] == sup_role:
                supervisor_entry = a
                break

    workflow_template = {
        "workflow_name": plan.workflow_name,
        "topology": plan.topology.value,
        "supervisor": supervisor_entry,
        "agents": assembled_agents,
        "shared_state_schema": plan.shared_state_schema,
        "routing_rules": plan.routing_rules,
    }

    final_status = "ready" if not failed_agents else "failed"
    _update_workflow(
        workflow_id,
        status=final_status,
        agents=assembled_agents,
        workflow_config=workflow_template,
        shared_state_schema=plan.shared_state_schema,
        error_log="; ".join(failed_agents) if failed_agents else None,
    )

    logger.info(
        "[BuildWorkflow] Workflow %s → %s (%d agents assembled)",
        workflow_id,
        final_status,
        len(assembled_agents),
    )

    return workflow_template
