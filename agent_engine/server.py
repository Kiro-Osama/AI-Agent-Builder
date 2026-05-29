"""
Agent Engine Server
=====================
Internal FastAPI server that runs DeepAgent instances in isolation.
"""
import json
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from core.langsmith_env import apply_langsmith_env
apply_langsmith_env()

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.deep_agent_runtime import run_deep_agent, stream_deep_agent
from core.mcp_adapter import load_mcp_tools_for_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Engine", version="1.0.0")


class AgentExecuteRequest(BaseModel):
    system_prompt: str
    user_message: str
    history: list[dict] = []
    skill_ids: list[str] | None = None
    mcp_configs: list[dict] = []
    mcp_user_configs: dict[str, dict] | None = None
    model: str | None = None
    images: list[dict] = []


class AgentExecuteResponse(BaseModel):
    response: str
    tool_calls: list[dict] = []
    model: str
    iterations: int = 1


async def _load_mcp_tools(request: AgentExecuteRequest):
    if not request.mcp_configs:
        return None
    try:
        tools = await load_mcp_tools_for_agent(
            request.mcp_configs,
            mcp_user_configs=request.mcp_user_configs,
        )
        logger.info("[AgentEngine] Loaded %d MCP tools", len(tools))
        return tools
    except Exception as e:
        logger.error("[AgentEngine] MCP tool loading failed: %s", e)
        return None


@app.post("/execute", response_model=AgentExecuteResponse)
async def execute_agent(request: AgentExecuteRequest):
    logger.info(
        "[AgentEngine] Execute: skills=%s, mcps=%d, model=%s",
        request.skill_ids or "all",
        len(request.mcp_configs),
        request.model or "default",
    )
    mcp_tools = await _load_mcp_tools(request)
    try:
        result = await run_deep_agent(
            system_prompt=request.system_prompt,
            user_message=request.user_message,
            history=request.history,
            mcp_tools=mcp_tools,
            skill_ids=request.skill_ids,
            model=request.model,
            images=request.images or [],
        )
        return AgentExecuteResponse(
            response=result["response"],
            tool_calls=result.get("tool_calls", []),
            model=result.get("model", "unknown"),
            iterations=result.get("iterations", 1),
        )
    except Exception as e:
        logger.error("[AgentEngine] Execution failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Agent execution failed: {str(e)}")


@app.post("/execute/stream")
async def execute_agent_stream(request: AgentExecuteRequest):
    """
    Stream DeepAgent execution as Server-Sent Events.
    Events:
      data: {"type": "tool_start", "tool": "...", "args": {...}}
      data: {"type": "tool_end",   "tool": "...", "result": "..."}
      data: {"type": "text",       "content": "..."}
      data: {"type": "done",       "tool_calls": [...], "model": "..."}
      data: {"type": "error",      "message": "..."}
    """
    logger.info(
        "[AgentEngine] Stream: skills=%s, mcps=%d, model=%s",
        request.skill_ids or "all",
        len(request.mcp_configs),
        request.model or "default",
    )
    mcp_tools = await _load_mcp_tools(request)

    async def event_generator():
        tool_calls_log: list[dict] = []
        effective_model = request.model or "unknown"
        final_text = ""

        try:
            async for chunk in stream_deep_agent(
                system_prompt=request.system_prompt,
                user_message=request.user_message,
                history=request.history,
                mcp_tools=mcp_tools,
                skill_ids=request.skill_ids,
                model=request.model,
            ):
                if not isinstance(chunk, dict):
                    logger.warning("[AgentEngine] Non-dict chunk type=%s: %s", type(chunk).__name__, str(chunk)[:200])
                    continue

                logger.info("[AgentEngine] Chunk keys: %s", list(chunk.keys()))
                # Log the value types for debugging
                for ck, cv in chunk.items():
                    cv_type = type(cv).__name__
                    cv_repr = str(cv)[:300]
                    logger.info("[AgentEngine] Chunk[%s] type=%s val=%s", ck, cv_type, cv_repr)

                # LangGraph astream() yields chunks keyed by node name:
                #   {"agent": {"messages": [AIMessage(...)]}}
                #   {"tools": {"messages": [ToolMessage(...)]}}
                # OR sometimes just {"messages": [...]}
                # We need to extract messages from any of these formats.
                messages = []

                if "messages" in chunk:
                    messages = chunk["messages"]
                else:
                    # LangGraph node-keyed format — extract messages from each node
                    for key, value in chunk.items():
                        if isinstance(value, dict) and "messages" in value:
                            messages.extend(value["messages"])
                        elif isinstance(value, list):
                            messages.extend(value)

                if not isinstance(messages, list):
                    messages = [messages]

                for msg in messages:
                    # ---- AIMessage with tool calls ----
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_name = tc.get("name", "unknown")
                            tool_args = tc.get("args", {})
                            tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": "", "success": True})
                            yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name, 'args': tool_args})}\n\n"

                    # ---- ToolMessage (result) ----
                    if hasattr(msg, "type") and msg.type == "tool":
                        result_content = str(getattr(msg, "content", ""))[:500]
                        for tc in reversed(tool_calls_log):
                            if not tc["result"]:
                                tc["result"] = result_content
                                break
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool': getattr(msg, 'name', 'tool'), 'result': result_content})}\n\n"

                    # ---- AIMessage with text content (no tool calls) ----
                    if hasattr(msg, "type") and msg.type in ("ai", "AIMessage", "AIMessageChunk"):
                        raw_content = getattr(msg, "content", "")

                        # Gemini returns content as list: [{'type': 'text', 'text': '...'}]
                        # OpenRouter/Ollama returns content as string
                        if isinstance(raw_content, list):
                            text_parts = []
                            for block in raw_content:
                                if isinstance(block, str):
                                    text_parts.append(block)
                                elif isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                            content = "\n".join(text_parts).strip()
                        elif isinstance(raw_content, str):
                            content = raw_content.strip()
                        else:
                            content = str(raw_content).strip() if raw_content else ""

                        if content and not (hasattr(msg, "tool_calls") and msg.tool_calls):
                            final_text = content
                            yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"

                        if hasattr(msg, "response_metadata"):
                            m = msg.response_metadata.get("model_name", "")
                            if m:
                                effective_model = m

                    # ---- Dict-based messages (fallback) ----
                    elif isinstance(msg, dict):
                        role = msg.get("role", msg.get("type", ""))
                        content = msg.get("content", "")
                        if role in ("ai", "assistant") and content:
                            final_text = content
                            yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"

        except Exception as e:
            logger.error("[AgentEngine] Stream error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'tool_calls': tool_calls_log, 'model': effective_model})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    skills_dir = os.getenv("SKILLS_DIR", "/app/skills/skills")
    workspace_dir = os.getenv("WORKSPACE_DIR", "/app/workspace")
    return {
        "status": "ok",
        "service": "agent-engine",
        "skills_dir_exists": os.path.isdir(skills_dir),
        "workspace_dir_exists": os.path.isdir(workspace_dir),
        "skills_count": len([
            d for d in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, d))
        ]) if os.path.isdir(skills_dir) else 0,
    }


if __name__ == "__main__":
    port = int(os.getenv("AGENT_ENGINE_PORT", "8001"))
    uvicorn.run("agent_engine.server:app", host="0.0.0.0", port=port, log_level="info")
