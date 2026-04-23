"""
Agent Engine Server
=====================
Internal FastAPI server that runs DeepAgent instances in isolation.
The main API container calls this service to execute agent tasks.

Each request:
    1. Receives system_prompt, user_message, history, skill_ids, mcp_configs
    2. Loads MCP tools via langchain_mcp_adapters
    3. Resolves skill directories (skills volume mounted read-only)
    4. Creates DeepAgent with FilesystemBackend (sandboxed workspace volume)
    5. Executes and returns response + tool_calls

This runs in its own Docker container with:
    - ./skills/skills:/app/skills/skills:ro  (read-only skill folders)
    - agent_workspace:/app/workspace         (sandboxed writable area)
    - /var/run/docker.sock                   (for MCP stdio containers)
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from core.langsmith_env import apply_langsmith_env

apply_langsmith_env()

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.deep_agent_runtime import run_deep_agent
from core.mcp_adapter import load_mcp_tools_for_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Engine", version="1.0.0")


# -----------------------------------------------
# Request / Response Models
# -----------------------------------------------

class AgentExecuteRequest(BaseModel):
    """Request to execute a single agent."""
    system_prompt: str
    user_message: str
    history: list[dict] = []
    skill_ids: list[str] | None = None
    mcp_configs: list[dict] = []
    mcp_user_configs: dict[str, dict] | None = None
    model: str | None = None


class AgentExecuteResponse(BaseModel):
    """Response from agent execution."""
    response: str
    tool_calls: list[dict] = []
    model: str
    iterations: int = 1


# -----------------------------------------------
# Endpoints
# -----------------------------------------------

@app.post("/execute", response_model=AgentExecuteResponse)
async def execute_agent(request: AgentExecuteRequest):
    """
    Execute a DeepAgent with the given config.

    This is the core execution endpoint. The main API container
    calls this to run an agent in isolation with:
    - Skills loaded via progressive disclosure (SKILL.md → read_file → execute)
    - MCP tools loaded via langchain_mcp_adapters
    - Sandboxed filesystem via FilesystemBackend
    """
    logger.info(
        "[AgentEngine] Execute: skills=%s, mcps=%d, model=%s",
        request.skill_ids or "all",
        len(request.mcp_configs),
        request.model or "default",
    )

    # Load MCP tools if any
    mcp_tools = None
    if request.mcp_configs:
        try:
            mcp_tools = await load_mcp_tools_for_agent(
                request.mcp_configs,
                mcp_user_configs=request.mcp_user_configs,
            )
            logger.info("[AgentEngine] Loaded %d MCP tools", len(mcp_tools))
        except Exception as e:
            logger.error("[AgentEngine] MCP tool loading failed: %s", e)

    # Execute DeepAgent
    try:
        result = await run_deep_agent(
            system_prompt=request.system_prompt,
            user_message=request.user_message,
            history=request.history,
            mcp_tools=mcp_tools,
            skill_ids=request.skill_ids,
            model=request.model,
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


@app.get("/health")
async def health():
    """Health check."""
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


# -----------------------------------------------
# Entry point
# -----------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("AGENT_ENGINE_PORT", "8001"))
    uvicorn.run(
        "agent_engine.server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
