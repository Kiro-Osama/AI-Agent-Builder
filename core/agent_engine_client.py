"""
Agent Engine Client
=====================
HTTP client for the main API to communicate with the agent-engine service.
The agent-engine runs in a separate Docker container for isolation.

Usage (from api/routers/chat.py):
    from core.agent_engine_client import execute_on_agent_engine
    result = await execute_on_agent_engine(system_prompt, user_message, ...)
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = os.getenv("AGENT_ENGINE_URL", "http://agent-engine:8001")
AGENT_ENGINE_TIMEOUT = int(os.getenv("AGENT_ENGINE_TIMEOUT", "120"))


async def execute_on_agent_engine(
    system_prompt: str,
    user_message: str,
    history: list[dict],
    skill_ids: list[str] | None = None,
    mcp_configs: list[dict] | None = None,
    mcp_user_configs: dict[str, dict] | None = None,
    model: str | None = None,
) -> dict:
    """
    Send an execution request to the agent-engine Docker service.

    This is the bridge between the API container and the isolated agent-engine.
    The agent-engine creates a DeepAgent with:
        - FilesystemBackend (sandboxed workspace volume)
        - Skills from read-only mounted skill folders
        - MCP tools loaded via langchain_mcp_adapters

    Args:
        system_prompt: Agent's system-level instructions
        user_message: Current user message
        history: Conversation history [{role, content}, ...]
        skill_ids: List of skill folder names to load
        mcp_configs: MCP container configs for tool loading
        mcp_user_configs: User-provided API keys per MCP
        model: Override model string

    Returns:
        {"response": str, "tool_calls": list, "model": str, "iterations": int}
    """
    payload = {
        "system_prompt": system_prompt,
        "user_message": user_message,
        "history": history,
        "skill_ids": skill_ids,
        "mcp_configs": mcp_configs or [],
        "mcp_user_configs": mcp_user_configs,
        "model": model,
    }

    url = f"{AGENT_ENGINE_URL}/execute"

    logger.info(
        "[AgentEngineClient] Sending to %s: skills=%s, mcps=%d",
        url,
        skill_ids or "all",
        len(mcp_configs) if mcp_configs else 0,
    )

    try:
        async with httpx.AsyncClient(timeout=AGENT_ENGINE_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            logger.info(
                "[AgentEngineClient] ✅ Got response: %d chars, %d tool_calls",
                len(result.get("response", "")),
                len(result.get("tool_calls", [])),
            )
            return result

    except httpx.TimeoutException:
        logger.error("[AgentEngineClient] Timeout after %ds", AGENT_ENGINE_TIMEOUT)
        return {
            "response": "Agent execution timed out. The task may be too complex.",
            "tool_calls": [],
            "model": model or "unknown",
            "iterations": 0,
        }
    except httpx.HTTPStatusError as e:
        logger.error("[AgentEngineClient] HTTP error: %s", e)
        return {
            "response": f"Agent engine error: {e.response.text[:500]}",
            "tool_calls": [],
            "model": model or "unknown",
            "iterations": 0,
        }
    except httpx.ConnectError:
        logger.error("[AgentEngineClient] Cannot connect to %s", url)
        return {
            "response": "Agent engine is not available. Ensure the agent-engine container is running.",
            "tool_calls": [],
            "model": model or "unknown",
            "iterations": 0,
        }
    except Exception as e:
        logger.error("[AgentEngineClient] Unexpected error: %s", e, exc_info=True)
        return {
            "response": f"Agent execution error: {str(e)}",
            "tool_calls": [],
            "model": model or "unknown",
            "iterations": 0,
        }
