"""
Workflow Router
================
Build, manage, and chat with multi-agent workflows.

Build endpoints:
  POST /workflow/build       — Submit a complex task for workflow planning + building
  GET  /workflow/{wf_id}     — Get workflow status and per-agent build progress
  GET  /workflows            — List all workflows
  POST /workflow/manual      — Manually define a workflow

Chat endpoints:
  POST /workflow/{wf_id}/chat       — Chat with a workflow
  GET  /workflow/{wf_id}/chat/info  — Get workflow info (agents, topology, state)
  GET  /workflow/{wf_id}/chat/state — Get shared state + execution log
  DELETE /workflow/{wf_id}/chat/session — End workflow session
"""
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from core.db import get_db
from core.models import Workflow, WorkflowExecution, BuildHistory
from core.workflow_session import (
    WorkflowSession,
    get_workflow_session,
    store_workflow_session,
    cleanup_workflow_session,
)
from core.ollama_client import use_llm_provider
from core.workflow_executor import execute_workflow

logger = logging.getLogger(__name__)

LlmProvider = Literal["openrouter", "ollama", "ollama_remote"]
router = APIRouter()

# Celery client for dispatching workflow build tasks
from celery import Celery

_celery = Celery("agent_builder", broker=settings.redis_url, backend=settings.redis_url)


# --------------------------------------------------
# Request / Response Models
# --------------------------------------------------

class WorkflowBuildRequest(BaseModel):
    query: str
    topology_hint: str | None = "auto"
    preferred_model: str | None = None
    llm_provider: LlmProvider | None = None


class WorkflowBuildResponse(BaseModel):
    workflow_id: str
    status: str
    message: str


class WorkflowChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    mcp_configs: dict[str, dict] | None = None
    llm_provider: LlmProvider | None = None


class WorkflowChatResponse(BaseModel):
    response: str
    responding_agent: str
    execution_path: list[str]
    conversation_id: str
    topology: str
    current_agent: str | None
    shared_state: dict
    tool_calls_count: int = 0


class ManualWorkflowRequest(BaseModel):
    name: str
    topology: str
    agents: list[dict]
    routing_rules: dict | None = None
    shared_state_schema: dict | None = None


# --------------------------------------------------
# Build Endpoints
# --------------------------------------------------

@router.post("/workflow/build", response_model=WorkflowBuildResponse)
async def build_workflow(
    request: WorkflowBuildRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit a complex task for multi-agent workflow planning and building."""
    workflow_id = f"wf-{uuid.uuid4().hex[:12]}"

    await db.execute(
        insert(Workflow).values(
            workflow_id=workflow_id,
            user_query=request.query,
            status="queued",
            topology="sequential",
        )
    )
    await db.commit()

    try:
        _celery.send_task(
            "worker.tasks.build_workflow.run_workflow_build",
            kwargs={
                "user_query": request.query,
                "workflow_id": workflow_id,
                "topology_hint": request.topology_hint,
                "preferred_model": request.preferred_model,
                "llm_provider": request.llm_provider,
            },
            queue="build",
        )
    except Exception as e:
        logger.error("Failed to dispatch workflow build: %s", e)
        await db.execute(
            update(Workflow)
            .where(Workflow.workflow_id == workflow_id)
            .values(status="failed", error_log=f"Dispatch error: {e}")
        )
        await db.commit()
        raise HTTPException(500, f"Task queue unavailable: {e}")

    return WorkflowBuildResponse(
        workflow_id=workflow_id,
        status="queued",
        message="Workflow build submitted. Poll /workflow/{workflow_id} for progress.",
    )


@router.get("/workflow/{workflow_id}")
async def get_workflow_status(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get workflow status including per-agent build progress."""
    result = await db.execute(
        select(Workflow).where(Workflow.workflow_id == workflow_id)
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(404, "Workflow not found")

    agent_build_status = []
    build_task_ids = wf.build_task_ids or []
    if build_task_ids:
        builds = await db.execute(
            select(BuildHistory).where(BuildHistory.task_id.in_(build_task_ids))
        )
        build_map = {b.task_id: b for b in builds.scalars().all()}

        for agent_def in (wf.agents or []):
            tid = agent_def.get("task_id", "")
            build = build_map.get(tid)
            agent_build_status.append({
                "role": agent_def.get("role", ""),
                "agent_name": agent_def.get("agent_name", ""),
                "task_id": tid,
                "status": build.status if build else "unknown",
                "current_node": build.current_node if build else None,
                "processing_log": build.processing_log if build else [],
            })

    return {
        **wf.to_dict(),
        "agent_build_status": agent_build_status,
    }


@router.get("/workflows")
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
):
    """List all workflows, optionally filtered by status."""
    query = select(Workflow).order_by(Workflow.created_at.desc())
    if status:
        query = query.where(Workflow.status == status)
    result = await db.execute(query)
    workflows = result.scalars().all()
    return {"workflows": [w.to_dict() for w in workflows]}


# --------------------------------------------------
# Manual Build
# --------------------------------------------------

@router.post("/workflow/manual")
async def manual_workflow_build(
    request: ManualWorkflowRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually define a workflow from existing agent builds."""
    workflow_id = f"wf-{uuid.uuid4().hex[:12]}"

    if request.topology not in ("sequential", "parallel", "supervisor", "swarm"):
        raise HTTPException(400, f"Invalid topology: {request.topology}")

    if len(request.agents) < 2:
        raise HTTPException(400, "At least 2 agents required for a workflow")

    # Validate that agent task_ids exist
    task_ids = [a.get("task_id") for a in request.agents if a.get("task_id")]
    if task_ids:
        builds = await db.execute(
            select(BuildHistory.task_id, BuildHistory.status, BuildHistory.result_template)
            .where(BuildHistory.task_id.in_(task_ids))
        )
        build_map = {r.task_id: r for r in builds.all()}

        enriched_agents = []
        for agent_def in request.agents:
            tid = agent_def.get("task_id")
            if tid and tid in build_map:
                row = build_map[tid]
                tmpl = row.result_template or {}
                built = tmpl.get("agents", [{}])[0] if tmpl.get("agents") else {}
                enriched = {
                    **agent_def,
                    "agent_name": agent_def.get("agent_name") or built.get("agent_name", "Agent"),
                    "system_prompt": agent_def.get("system_prompt") or built.get("system_prompt", ""),
                    "model": agent_def.get("model") or built.get("assigned_openrouter_model", ""),
                    "selected_mcps": built.get("selected_mcps", []),
                    "selected_skills": built.get("selected_skills", []),
                }
                enriched_agents.append(enriched)
            else:
                enriched_agents.append(agent_def)
    else:
        enriched_agents = request.agents

    from core.workflow_topologies import TopologyType, build_routing_rules, AgentRole
    topology = TopologyType(request.topology)
    agent_roles = [AgentRole(role=a.get("role", f"agent_{i}"), agent_name=a.get("agent_name", ""), sub_task="") for i, a in enumerate(enriched_agents)]
    routing = request.routing_rules or build_routing_rules(topology, agent_roles)

    workflow_config = {
        "workflow_name": request.name,
        "topology": request.topology,
        "agents": enriched_agents,
        "routing_rules": routing,
        "shared_state_schema": request.shared_state_schema or {},
    }

    await db.execute(
        insert(Workflow).values(
            workflow_id=workflow_id,
            name=request.name,
            user_query=f"Manual workflow: {request.name}",
            topology=request.topology,
            agents=enriched_agents,
            workflow_config=workflow_config,
            shared_state_schema=request.shared_state_schema or {},
            build_task_ids=task_ids,
            status="ready",
        )
    )
    await db.commit()

    return {
        "workflow_id": workflow_id,
        "status": "ready",
        "workflow_config": workflow_config,
    }


# --------------------------------------------------
# Chat Endpoints
# --------------------------------------------------

_wf_conversations: dict[str, list[dict]] = {}


@router.post("/workflow/{workflow_id}/chat", response_model=WorkflowChatResponse)
async def chat_with_workflow(
    workflow_id: str,
    request: WorkflowChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Chat with a multi-agent workflow. Messages are routed through the topology."""
    conv_id = request.conversation_id or str(uuid.uuid4())
    session_key = f"{workflow_id}:{conv_id}"

    wf_session = get_workflow_session(session_key)

    if not wf_session:
        # Load workflow from DB
        result = await db.execute(
            select(Workflow).where(Workflow.workflow_id == workflow_id)
        )
        wf = result.scalar_one_or_none()
        if not wf:
            raise HTTPException(404, "Workflow not found")
        if wf.status != "ready":
            raise HTTPException(400, f"Workflow not ready (status: {wf.status})")

        wf_config = wf.workflow_config or {}
        agents = wf.agents or wf_config.get("agents", [])
        routing_rules = wf_config.get("routing_rules", {})

        wf_session = WorkflowSession(
            workflow_id=workflow_id,
            topology=wf.topology,
            agents=agents,
            routing_rules=routing_rules,
            shared_state_schema=wf.shared_state_schema,
            mcp_user_configs=request.mcp_configs,
        )

        try:
            await wf_session.start()
        except Exception as e:
            logger.error("Failed to start workflow session: %s", e)
            raise HTTPException(503, f"Failed to start agent sessions: {e}")

        store_workflow_session(session_key, wf_session)

        await db.execute(
            insert(WorkflowExecution).values(
                workflow_id=workflow_id,
                conversation_id=conv_id,
                status="active",
                current_agent=wf_session.current_agent,
            )
        )
        await db.commit()

    try:
        with use_llm_provider(request.llm_provider):
            result = await execute_workflow(wf_session, request.message)
    except Exception as e:
        logger.error("Workflow execution error: %s", e, exc_info=True)
        raise HTTPException(500, f"Workflow execution failed: {e}")

    # Persist execution state
    try:
        await db.execute(
            update(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.conversation_id == conv_id,
            )
            .values(
                shared_state=wf_session.shared_state,
                execution_log=wf_session.execution_log[-50:],
                current_agent=wf_session.current_agent,
            )
        )
        await db.commit()
    except Exception as e:
        logger.warning("Failed to persist workflow execution state: %s", e)

    return WorkflowChatResponse(
        response=result.response,
        responding_agent=result.responding_agent,
        execution_path=result.execution_path,
        conversation_id=conv_id,
        topology=wf_session.topology.value,
        current_agent=wf_session.current_agent,
        shared_state=wf_session.shared_state,
        tool_calls_count=len(result.tool_calls),
    )


@router.get("/workflow/{workflow_id}/chat/info")
async def get_workflow_chat_info(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get workflow info for the chat UI."""
    result = await db.execute(
        select(Workflow).where(Workflow.workflow_id == workflow_id)
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(404, "Workflow not found")

    agents_info = []
    config_required = []
    for agent_def in (wf.agents or []):
        agents_info.append({
            "role": agent_def.get("role", ""),
            "agent_name": agent_def.get("agent_name", ""),
            "sub_task": agent_def.get("sub_task", ""),
            "model": agent_def.get("model", ""),
            "mcps_count": len(agent_def.get("selected_mcps", [])),
            "skills_count": len(agent_def.get("selected_skills", [])),
        })
        for mcp in agent_def.get("selected_mcps", []):
            if mcp.get("requires_user_config"):
                config_required.append({
                    "mcp_name": mcp.get("mcp_name"),
                    "config_schema": mcp.get("config_schema", []),
                })

    routing = (wf.workflow_config or {}).get("routing_rules", {})

    return {
        "workflow_id": wf.workflow_id,
        "name": wf.name,
        "description": wf.description,
        "topology": wf.topology,
        "status": wf.status,
        "agents": agents_info,
        "routing_rules": routing,
        "shared_state_schema": wf.shared_state_schema,
        "config_required": config_required,
        "user_query": wf.user_query,
    }


@router.get("/workflow/{workflow_id}/chat/state")
async def get_workflow_state(
    workflow_id: str,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get current shared state and execution log for a workflow session."""
    session_key = f"{workflow_id}:{conversation_id}"
    wf_session = get_workflow_session(session_key)

    if wf_session:
        return {
            "shared_state": wf_session.shared_state,
            "execution_log": wf_session.execution_log[-100:],
            "current_agent": wf_session.current_agent,
            "active": wf_session.active,
        }

    result = await db.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.workflow_id == workflow_id,
            WorkflowExecution.conversation_id == conversation_id,
        )
    )
    exe = result.scalar_one_or_none()
    if not exe:
        raise HTTPException(404, "Workflow execution not found")

    return {
        "shared_state": exe.shared_state,
        "execution_log": exe.execution_log,
        "current_agent": exe.current_agent,
        "active": exe.status == "active",
    }


@router.delete("/workflow/{workflow_id}/chat/session")
async def end_workflow_session(workflow_id: str, conversation_id: str):
    """End a workflow chat session and cleanup all agent MCP containers."""
    session_key = f"{workflow_id}:{conversation_id}"
    await cleanup_workflow_session(session_key)
    return {"status": "cleaned_up", "workflow_id": workflow_id, "conversation_id": conversation_id}
