"""
Import / Export Router
=======================
Export a completed agent or workflow to a portable JSON file, and
re-import that file to recreate the same agent/workflow in any instance.

Endpoints:
  GET  /api/v1/export/agent/{task_id}       → download agent JSON
  GET  /api/v1/export/workflow/{workflow_id} → download workflow JSON
  POST /api/v1/import                        → upload JSON, recreate entry, return new IDs
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import BuildHistory, Workflow

logger = logging.getLogger(__name__)
router = APIRouter()

EXPORT_VERSION = "1"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _json_response(payload: dict, filename: str) -> Response:
    content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export/agent/{task_id}")
async def export_agent(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Download a completed agent template as a portable JSON file.
    The file can be shared and re-imported on any instance.
    """
    from sqlalchemy import select

    result = await db.execute(
        select(BuildHistory).where(BuildHistory.task_id == task_id)
    )
    build = result.scalar_one_or_none()
    if not build:
        raise HTTPException(404, f"Agent build '{task_id}' not found")
    if not build.result_template:
        raise HTTPException(409, "Build has no completed template yet")

    agent_name = "agent"
    tmpl = build.result_template or {}
    agents = tmpl.get("agents") or []
    if agents and isinstance(agents[0], dict):
        agent_name = agents[0].get("agent_name", "agent")

    payload = {
        "export_version": EXPORT_VERSION,
        "export_type": "agent",
        "exported_at": _now_iso(),
        "source_query": build.user_query or "",
        "template": build.result_template,
    }

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in agent_name)
    filename = f"agent_{safe_name}_{task_id[:8]}.json"
    logger.info("[Export] agent %s → %s", task_id, filename)
    return _json_response(payload, filename)


@router.get("/export/workflow/{workflow_id}")
async def export_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    """
    Download a workflow definition as a portable JSON file.
    """
    from sqlalchemy import select

    result = await db.execute(
        select(Workflow).where(Workflow.workflow_id == workflow_id)
    )
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found")
    if wf.status not in ("ready", "building", "awaiting_plan_approval"):
        raise HTTPException(409, f"Workflow status is '{wf.status}' — cannot export yet")

    payload = {
        "export_version": EXPORT_VERSION,
        "export_type": "workflow",
        "exported_at": _now_iso(),
        "source_query": wf.user_query or "",
        "workflow": {
            "name": wf.name or "Imported Workflow",
            "description": wf.description or "",
            "topology": wf.topology,
            "agents": wf.agents or [],
            "workflow_config": wf.workflow_config or {},
            "shared_state_schema": wf.shared_state_schema or {},
        },
    }

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (wf.name or "workflow"))
    filename = f"workflow_{safe_name}_{workflow_id[-8:]}.json"
    logger.info("[Export] workflow %s → %s", workflow_id, filename)
    return _json_response(payload, filename)


# ─────────────────────────────────────────────────────────────────────────────
# Import
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/import")
async def import_config(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Import a previously exported agent or workflow JSON.
    Creates a new DB entry and returns the IDs needed to open chat.

    Returns:
        {
          "import_type": "agent" | "workflow",
          "task_id": "..." | null,
          "workflow_id": "..." | null,
          "chat_url": "/chat.html?task_id=..." | "/workflow-chat.html?workflow_id=...",
          "name": "..."
        }
    """
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(400, "Only .json files are accepted")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:  # 5 MB guard
        raise HTTPException(413, "File too large (max 5 MB)")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise HTTPException(422, "JSON root must be an object")

    export_type = data.get("export_type")
    if export_type not in ("agent", "workflow"):
        raise HTTPException(
            422,
            "Unrecognised export file. Missing or invalid 'export_type' "
            "(expected 'agent' or 'workflow')."
        )

    # ── Agent import ─────────────────────────────────────────────────────────
    if export_type == "agent":
        template = data.get("template")
        if not isinstance(template, dict) or not template.get("agents"):
            raise HTTPException(422, "Export file has no valid agent template")

        task_id = f"import-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        agent_name = (
            (template.get("agents") or [{}])[0].get("agent_name", "Imported Agent")
        )
        source_query = data.get("source_query") or f"[Import] {agent_name}"

        mcps = []
        skills = []
        agents_list = template.get("agents") or []
        if agents_list and isinstance(agents_list[0], dict):
            mcps = agents_list[0].get("selected_mcps") or []
            skills = agents_list[0].get("selected_skills") or []

        await db.execute(
            insert(BuildHistory).values(
                task_id=task_id,
                user_query=source_query,
                status="completed",
                current_node="imported",
                result_template=template,
                selected_mcps=mcps,
                selected_skills=skills,
                processing_log=[{
                    "timestamp": now.isoformat(),
                    "node": "import",
                    "message": f"Imported from file: {file.filename}",
                }],
                started_at=now,
                completed_at=now,
            )
        )
        await db.commit()
        logger.info("[Import] agent task_id=%s  name=%s", task_id, agent_name)
        return {
            "import_type": "agent",
            "task_id": task_id,
            "workflow_id": None,
            "chat_url": f"/chat.html?task_id={task_id}",
            "name": agent_name,
        }

    # ── Workflow import ───────────────────────────────────────────────────────
    wf_data = data.get("workflow")
    if not isinstance(wf_data, dict) or not wf_data.get("agents"):
        raise HTTPException(422, "Export file has no valid workflow definition")

    topology = wf_data.get("topology", "sequential")
    if topology not in ("sequential", "parallel", "supervisor", "swarm"):
        topology = "sequential"

    wf_name = wf_data.get("name") or "Imported Workflow"
    workflow_id = f"wf-import-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    source_query = data.get("source_query") or f"[Import] {wf_name}"

    agents = wf_data.get("agents") or []
    workflow_config = wf_data.get("workflow_config") or {}
    shared_state_schema = wf_data.get("shared_state_schema") or {}

    await db.execute(
        insert(Workflow).values(
            workflow_id=workflow_id,
            name=wf_name,
            description=wf_data.get("description", ""),
            user_query=source_query,
            topology=topology,
            agents=agents,
            workflow_config=workflow_config,
            shared_state_schema=shared_state_schema,
            status="ready",
            build_task_ids=[a.get("task_id") for a in agents if a.get("task_id")],
        )
    )
    await db.commit()
    logger.info("[Import] workflow workflow_id=%s  name=%s", workflow_id, wf_name)
    return {
        "import_type": "workflow",
        "task_id": None,
        "workflow_id": workflow_id,
        "chat_url": f"/workflow-chat.html?workflow_id={workflow_id}",
        "name": wf_name,
    }
