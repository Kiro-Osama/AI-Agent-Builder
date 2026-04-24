"""
Chat Router - DeepAgent Execution
=====================================
POST /api/v1/chat/{task_id}   - Chat with a built agent
GET  /api/v1/chat/{task_id}/info - Get agent info

On each message:
    1. Load agent config from build history (system_prompt, skills, mcps)
    2. Send execution request to the agent-engine Docker service
    3. The agent-engine creates a DeepAgent with:
       - Skills loaded via progressive disclosure (SKILL.md → scripts/ → reference/)
       - MCP tools loaded via langchain_mcp_adapters
       - Sandboxed workspace via FilesystemBackend
    4. Return response + tool calls
"""
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent_engine_client import execute_on_agent_engine
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

    # Send to agent-engine Docker service
    selected_mcps = config.get("selected_mcps", [])
    
    system_prompt = config["system_prompt"]
    
    # Inform the agent about any local directories mounted to /user_dir
    if request.mcp_configs:
        for mcp_name, user_cfg in request.mcp_configs.items():
            if "allowed_directory" in user_cfg and user_cfg["allowed_directory"].strip():
                host_dir = user_cfg["allowed_directory"].strip()
                system_prompt += (
                    f"\n\n[System Note: The user's local directory '{host_dir}' has been securely mounted to '/user_dir'. "
                    f"This is your PRIMARY working directory. If the user asks to list or organize files without specifying a path, ASSUME they mean '/user_dir'. "
                    f"If the user provides a path starting with '{host_dir}' (or any subfolder), you MUST replace the '{host_dir}' part with '/user_dir'. For example, if they say '{host_dir}\\Notebooks', you MUST access '/user_dir/Notebooks'. DO NOT try to access the literal path '{host_dir}' directly! "
                    f"CRITICAL: You have default tools (e.g. 'move_file', 'read_file') and MCP tools with the SAME names. "
                    f"The default tools are strictly sandboxed to '/workspace' and will throw 'access denied - path outside allowed directories' if you try to use them on '/user_dir'. "
                    f"If you receive this 'access denied' error, it means you accidentally used the default tool! You MUST retry using the MCP version of the tool, or if you can't distinguish them, write a Python script using the 'execute' tool to do file operations, or ask the user for clarification. "
                    f"Even if the user says 'use ls tool', you should interpret that as 'use list_directory' on '/user_dir'."
                )

    try:
        result = await execute_on_agent_engine(
            system_prompt=system_prompt,
            user_message=request.message,
            history=history,
            skill_ids=config.get("selected_skills"),
            mcp_configs=selected_mcps,
            mcp_user_configs=request.mcp_configs,
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
            mcps_connected=len(selected_mcps),
        )

    except Exception as e:
        logger.error("[Chat] Agent engine error: %s", e, exc_info=True)
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
