"""
Chat Router - Real Agent Execution
=====================================
POST /api/v1/chat/{task_id}   - Chat with a built agent (real tool calling)
GET  /api/v1/chat/{task_id}/info - Get agent info

On first message:
    1. Load agent config from build history
    2. Start MCP container sessions
    3. Run agent loop (ReAct: LLM ↔ MCP tools)

Subsequent messages:
    Reuse existing MCP sessions + conversation history
"""
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent_loop import run_agent_loop
from core.agent_session import (
    cleanup_sessions_matching_conversation_id,
    create_session,
    get_session,
    session_key as composite_session_key,
)
from core.db import get_db
from core.models import BuildHistory

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory: composite key task_id:conversation_id -> message list
conversations: dict[str, list[dict]] = {}

# Cache agent configs loaded from DB (keyed by task_id)
agent_configs: dict[str, dict] = {}

DEFAULT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "openrouter/free")


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str | None = None  # Override model


class ToolCallInfo(BaseModel):
    tool: str
    args: dict
    result: str
    success: bool = True


class ChatResponse(BaseModel):
    response: str
    agent_name: str
    model: str
    conversation_id: str
    tool_calls: list[ToolCallInfo] = []
    iterations: int = 1
    mcps_connected: int = 0


async def _load_agent_config(db: AsyncSession, task_id: str) -> dict:
    """Load and cache agent template for this build task."""
    if task_id in agent_configs:
        return agent_configs[task_id]

    result = await db.execute(
        select(BuildHistory).where(BuildHistory.task_id == task_id)
    )
    build = result.scalar_one_or_none()
    if not build or not build.result_template:
        raise HTTPException(404, "Build not found or not completed")

    template = build.result_template
    agents = template.get("agents", [])
    if not agents:
        raise HTTPException(400, "No agents in template")

    agent = agents[0]
    cfg = {
        "agent_name": agent.get("agent_name", "AI_Assistant"),
        "system_prompt": agent.get("system_prompt", "You are a helpful AI assistant."),
        "model": agent.get("assigned_openrouter_model", DEFAULT_MODEL),
        "selected_mcps": agent.get("selected_mcps", []),
        "selected_skills": agent.get("selected_skills", []),
    }
    agent_configs[task_id] = cfg
    return cfg


@router.post("/chat/{task_id}", response_model=ChatResponse)
async def chat_with_agent(
    task_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a message to a built agent.
    The agent uses real MCP tools via JSON-RPC — not simulated.
    """
    config = await _load_agent_config(db, task_id)

    conv_id = request.conversation_id or str(uuid.uuid4())
    key = composite_session_key(task_id, conv_id)

    if key not in conversations:
        conversations[key] = []

    history = conversations[key]

    agent_session = get_session(key)
    if not agent_session:
        agent_session = create_session(key)
        selected_mcps = config.get("selected_mcps", [])

        if selected_mcps:
            logger.info(
                f"[Chat] Starting MCP session for {key}: "
                f"{[m.get('mcp_name') for m in selected_mcps]}"
            )
            try:
                await agent_session.start(selected_mcps)
            except Exception as e:
                logger.error(f"[Chat] Failed to start MCP session: {e}")

    if request.model:
        model = request.model
    else:
        model = config["model"]
        if os.getenv("APP_ENV") == "development":
            if any(x in model for x in ["claude", "gpt-4", "gemini-pro"]):
                model = DEFAULT_MODEL

    try:
        result = await run_agent_loop(
            session=agent_session,
            system_prompt=config["system_prompt"],
            history=history,
            user_message=request.message,
            model=model,
        )

        response_text = result["response"]

        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": response_text})

        return ChatResponse(
            response=response_text,
            agent_name=config["agent_name"],
            model=result.get("model", model),
            conversation_id=conv_id,
            tool_calls=[ToolCallInfo(**tc) for tc in result.get("tool_calls", [])],
            iterations=result.get("iterations", 1),
            mcps_connected=len(agent_session.containers),
        )

    except Exception as e:
        logger.error(f"[Chat] Agent loop error: {e}", exc_info=True)
        raise HTTPException(500, f"Chat failed: {str(e)}")


@router.get("/chat/{task_id}/info")
async def get_agent_info(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get agent info for a completed build."""
    result = await db.execute(
        select(BuildHistory).where(BuildHistory.task_id == task_id)
    )
    build = result.scalar_one_or_none()
    if not build or not build.result_template:
        raise HTTPException(404, "Build not found")

    template = build.result_template
    agents = template.get("agents", [])
    agent = agents[0] if agents else {}

    return {
        "task_id": task_id,
        "agent_name": agent.get("agent_name", "AI_Assistant"),
        "model": agent.get("assigned_openrouter_model", "unknown"),
        "system_prompt": agent.get("system_prompt", ""),
        "selected_mcps": agent.get("selected_mcps", []),
        "selected_skills": agent.get("selected_skills", []),
        "project_type": template.get("project_type", "single_agent"),
        "user_query": build.user_query,
    }


@router.delete("/chat/{conversation_id}/session")
async def end_session(conversation_id: str):
    """Explicitly end a chat session and cleanup MCP containers."""
    await cleanup_sessions_matching_conversation_id(conversation_id)
    # Remove all conversation histories for this conversation_id across tasks
    keys_to_drop = [k for k in list(conversations.keys()) if k.endswith(f":{conversation_id}")]
    for k in keys_to_drop:
        conversations.pop(k, None)
    return {"status": "cleaned_up", "conversation_id": conversation_id}
