"""
Chat Router - DeepAgent Execution
=====================================
POST /api/v1/chat/{task_id}   - Chat with a built agent (DeepAgent + MCP tools)
GET  /api/v1/chat/{task_id}/info - Get agent info

On first message:
    1. Load agent config from build history
    2. Load MCP tools via langchain_mcp_adapters
    3. Create DeepAgent with skills + MCP tools + FilesystemBackend
    4. Execute agent (progressive skill disclosure, sub-agent spawning)

Subsequent messages:
    Reuse conversation history, re-create DeepAgent per request
    (DeepAgent is stateless; history is passed in messages)
"""
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.deep_agent_runtime import run_deep_agent
from core.mcp_adapter import load_mcp_tools_for_agent
from core.db import get_db
from core.mcp_user_config import mcp_config_required_for_modal
from core.models import BuildHistory

logger = logging.getLogger(__name__)

LlmProvider = Literal["openrouter", "ollama", "ollama_remote", "gemini"]
router = APIRouter()

# In-memory: composite key task_id:conversation_id -> message list
conversations: dict[str, list[dict]] = {}

# Cache agent configs loaded from DB (keyed by task_id)
agent_configs: dict[str, dict] = {}

DEFAULT_MODEL = os.getenv("DEEPAGENT_MODEL", os.getenv("DEFAULT_CHAT_MODEL", "gemini-3.1-flash-lite-preview"))


def _session_key(task_id: str, conversation_id: str) -> str:
    """Composite key so chat state cannot leak across different builds."""
    return f"{task_id}:{conversation_id}"


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str | None = None
    mcp_configs: dict[str, dict] | None = None  # {mcp_name: {KEY: value}}
    llm_provider: LlmProvider | None = None


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


def _resolve_model(request_model: str | None, config_model: str, llm_provider: str | None) -> str:
    """
    Resolve which model to use based on request, config, and provider.
    Supports: gemini, ollama, openrouter.
    """
    if request_model:
        return request_model

    if llm_provider == "ollama":
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3.5:4b-q4_K_M")
        return f"ollama:{ollama_model}"

    if llm_provider == "ollama_remote":
        remote_model = os.getenv("OLLAMA_REMOTE_MODEL", "qwen3.5:4b")
        return f"ollama:{remote_model}"

    if llm_provider == "gemini" or os.getenv("GOOGLE_API_KEY", "").strip():
        return os.getenv("DEEPAGENT_MODEL", "gemini-3.1-flash-lite-preview")

    # Use the model from build config
    return config_model or DEFAULT_MODEL


@router.post("/chat/{task_id}", response_model=ChatResponse)
async def chat_with_agent(
    task_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a message to a built agent.
    Uses DeepAgent with progressive skill disclosure and MCP tools.
    """
    config = await _load_agent_config(db, task_id)

    conv_id = request.conversation_id or str(uuid.uuid4())
    key = _session_key(task_id, conv_id)

    if key not in conversations:
        conversations[key] = []

    history = conversations[key]

    # Resolve model
    model = _resolve_model(request.model, config["model"], request.llm_provider)

    # Load MCP tools via langchain_mcp_adapters
    selected_mcps = config.get("selected_mcps", [])
    mcp_tools = []
    if selected_mcps:
        try:
            mcp_tools = await load_mcp_tools_for_agent(
                selected_mcps,
                mcp_user_configs=request.mcp_configs,
            )
            logger.info(
                "[Chat] Loaded %d MCP tools for %s",
                len(mcp_tools), config["agent_name"],
            )
        except Exception as e:
            logger.error("[Chat] Failed to load MCP tools: %s", e)

    # Run DeepAgent
    try:
        result = await run_deep_agent(
            system_prompt=config["system_prompt"],
            user_message=request.message,
            history=history,
            mcp_tools=mcp_tools if mcp_tools else None,
            skill_ids=config.get("selected_skills"),
            model=model,
        )

        response_text = result["response"]

        # Update conversation history
        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": response_text})

        return ChatResponse(
            response=response_text,
            agent_name=config["agent_name"],
            model=result.get("model", model),
            conversation_id=conv_id,
            tool_calls=[ToolCallInfo(**tc) for tc in result.get("tool_calls", [])],
            iterations=result.get("iterations", 1),
            mcps_connected=len(mcp_tools),
        )

    except Exception as e:
        logger.error("[Chat] Agent loop error: %s", e, exc_info=True)
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

    selected_mcps = agent.get("selected_mcps", [])
    config_required = await mcp_config_required_for_modal(db, selected_mcps)

    return {
        "task_id": task_id,
        "agent_name": agent.get("agent_name", "AI_Assistant"),
        "model": agent.get("assigned_openrouter_model", "unknown"),
        "system_prompt": agent.get("system_prompt", ""),
        "selected_mcps": selected_mcps,
        "selected_skills": agent.get("selected_skills", []),
        "project_type": template.get("project_type", "single_agent"),
        "user_query": build.user_query,
        "config_required": config_required,
    }


@router.delete("/chat/{conversation_id}/session")
async def end_session(conversation_id: str):
    """Explicitly end a chat session and cleanup."""
    # Remove all conversation histories for this conversation_id across tasks
    keys_to_drop = [k for k in list(conversations.keys()) if k.endswith(f":{conversation_id}")]
    for k in keys_to_drop:
        conversations.pop(k, None)
    return {"status": "cleaned_up", "conversation_id": conversation_id}
