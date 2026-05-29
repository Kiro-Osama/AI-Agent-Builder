"""
Agent Engine Client
=====================
HTTP client for the main API to communicate with the agent-engine service.
"""
import asyncio
import json
import logging
import os
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

AGENT_ENGINE_URL = os.getenv("AGENT_ENGINE_URL", "http://agent-engine:8001")
AGENT_ENGINE_TIMEOUT = int(os.getenv("AGENT_ENGINE_TIMEOUT", "600"))

_SENTINEL = object()  # marks end of queue


async def execute_on_agent_engine(
    system_prompt: str,
    user_message: str,
    history: list[dict],
    skill_ids: list[str] | None = None,
    mcp_configs: list[dict] | None = None,
    mcp_user_configs: dict[str, dict] | None = None,
    model: str | None = None,
    images: list[dict] | None = None,
) -> dict:
    payload = {
        "system_prompt": system_prompt,
        "user_message": user_message,
        "history": history,
        "skill_ids": skill_ids,
        "mcp_configs": mcp_configs or [],
        "mcp_user_configs": mcp_user_configs,
        "model": model,
        "images": images or [],
    }

    url = f"{AGENT_ENGINE_URL}/execute"
    logger.info("[AgentEngineClient] Sending to %s: skills=%s, mcps=%d", url, skill_ids or "all", len(mcp_configs) if mcp_configs else 0)

    try:
        async with httpx.AsyncClient(timeout=AGENT_ENGINE_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            logger.info("[AgentEngineClient] Got response: %d chars, %d tool_calls", len(result.get("response", "")), len(result.get("tool_calls", [])))
            return result
    except httpx.TimeoutException:
        return {"response": "Agent execution timed out.", "tool_calls": [], "model": model or "unknown", "iterations": 0}
    except httpx.HTTPStatusError as e:
        return {"response": f"Agent engine error: {e.response.text[:500]}", "tool_calls": [], "model": model or "unknown", "iterations": 0}
    except httpx.ConnectError:
        return {"response": "Agent engine is not available.", "tool_calls": [], "model": model or "unknown", "iterations": 0}
    except Exception as e:
        logger.error("[AgentEngineClient] Unexpected error: %s", e, exc_info=True)
        return {"response": f"Agent execution error: {str(e)}", "tool_calls": [], "model": model or "unknown", "iterations": 0}


async def _sse_reader(url: str, payload: dict, queue: asyncio.Queue, model: str | None):
    """
    Background task: reads SSE from agent-engine and pushes events into the queue.
    Runs fully inside its own context — no yield, no GeneratorExit issues.
    """
    got_done = False
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(AGENT_ENGINE_TIMEOUT, connect=30.0),
        ) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if not data_str:
                            continue
                        try:
                            event = json.loads(data_str)
                            await queue.put(event)
                            if event.get("type") == "done":
                                got_done = True
                        except json.JSONDecodeError:
                            continue
    except httpx.ConnectError:
        await queue.put({"type": "error", "message": "Agent engine is not available."})
    except httpx.TimeoutException:
        await queue.put({"type": "error", "message": "Agent execution timed out."})
    except Exception as e:
        logger.error("[AgentEngineClient] SSE reader error: %s", e, exc_info=True)
        await queue.put({"type": "error", "message": str(e)})

    if not got_done:
        await queue.put({"type": "done", "tool_calls": [], "model": model or "unknown"})

    await queue.put(_SENTINEL)


async def stream_from_agent_engine(
    system_prompt: str,
    user_message: str,
    history: list[dict],
    skill_ids: list[str] | None = None,
    mcp_configs: list[dict] | None = None,
    mcp_user_configs: dict[str, dict] | None = None,
    model: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Stream execution events from agent-engine via SSE.
    Uses asyncio.Queue to decouple httpx streaming from the generator yield.
    This avoids the 'async generator ignored GeneratorExit' error.
    """
    payload = {
        "system_prompt": system_prompt,
        "user_message": user_message,
        "history": history,
        "skill_ids": skill_ids,
        "mcp_configs": mcp_configs or [],
        "mcp_user_configs": mcp_user_configs,
        "model": model,
        "images": [],
    }

    url = f"{AGENT_ENGINE_URL}/execute/stream"
    logger.info("[AgentEngineClient] Streaming from %s", url)

    queue: asyncio.Queue = asyncio.Queue()
    reader_task = asyncio.create_task(_sse_reader(url, payload, queue, model))

    try:
        while True:
            event = await queue.get()
            if event is _SENTINEL:
                break
            yield event
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass
