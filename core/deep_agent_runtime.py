"""
DeepAgent Runtime Engine
=========================
Replaces core/agent_loop.py with deepagents-based execution.

Architecture:
    - Uses create_deep_agent() from the deepagents library (built on LangGraph)
    - Skills are loaded via progressive disclosure (frontmatter → on-demand read_file)
    - MCP tools are loaded via langchain_mcp_adapters
    - LLM: ChatGoogleGenerativeAI (Gemini) primary, OpenRouter/Ollama fallback
    - Sandboxing: FilesystemBackend with virtual_mode for safe execution

This module is the drop-in replacement for the old ReAct loop.
The old agent_loop.py injected the entire SKILL.md into the system prompt;
this new approach uses DeepAgent's progressive disclosure so the agent
reads skill files on-demand via read_file and executes scripts via execute.
"""
import json
import logging
import os
from typing import Any

import nest_asyncio

nest_asyncio.apply()

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

logger = logging.getLogger(__name__)

# -----------------------------------------------
# Environment Configuration
# -----------------------------------------------
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
DEEPAGENT_MODEL = os.getenv("DEEPAGENT_MODEL", "gemini-3.1-flash-lite-preview")
DEEPAGENT_TEMPERATURE = float(os.getenv("DEEPAGENT_TEMPERATURE", "0.2"))

SKILLS_DIR = os.getenv("SKILLS_DIR", os.path.join(os.path.dirname(__file__), "..", "skills", "skills"))
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", os.getenv("WORKSPACE_PATH", "/workspace"))

MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "15"))


def _resolve_skills_dir() -> str:
    """Resolve the absolute path to the skills directory."""
    path = os.path.abspath(SKILLS_DIR)
    if os.path.isdir(path):
        return path
    # Fallback: try relative to project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    fallback = os.path.join(project_root, "skills", "skills")
    if os.path.isdir(fallback):
        return fallback
    logger.warning("Skills directory not found at %s or %s", path, fallback)
    return path


# -----------------------------------------------
# LLM Factory — Gemini primary, OpenRouter/Ollama fallback
# -----------------------------------------------
def create_llm(model: str | None = None, temperature: float | None = None):
    """
    Create a LangChain-compatible LLM instance.

    Priority:
        1. If model starts with "ollama:" → use Ollama via ChatOpenAI
        2. If GOOGLE_API_KEY is set → use ChatGoogleGenerativeAI (Gemini)
        3. Fallback → use ChatOpenAI pointed at OpenRouter
    """
    effective_model = model or DEEPAGENT_MODEL
    effective_temp = temperature if temperature is not None else DEEPAGENT_TEMPERATURE

    # --- Ollama route ---
    if effective_model.startswith("ollama:"):
        from langchain_openai import ChatOpenAI

        ollama_tag = effective_model.split(":", 1)[1]
        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

        logger.info("[DeepAgent] Using Ollama: %s @ %s", ollama_tag, ollama_base)
        return ChatOpenAI(
            model=ollama_tag,
            base_url=f"{ollama_base}/v1",
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            temperature=effective_temp,
        )

    # --- Gemini route (primary) ---
    if GOOGLE_API_KEY:
        from langchain_google_genai import ChatGoogleGenerativeAI

        logger.info("[DeepAgent] Using Gemini: %s", effective_model)
        return ChatGoogleGenerativeAI(
            model=effective_model,
            temperature=effective_temp,
            google_api_key=GOOGLE_API_KEY,
        )

    # --- OpenRouter fallback ---
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        from langchain_openai import ChatOpenAI

        openrouter_base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        logger.info("[DeepAgent] Using OpenRouter fallback: %s", effective_model)
        return ChatOpenAI(
            model=effective_model,
            base_url=openrouter_base,
            api_key=openrouter_key,
            temperature=effective_temp,
            default_headers={
                "HTTP-Referer": "https://agent-builder.local",
                "X-Title": "Agent Builder V5 DeepAgent",
            },
        )

    raise RuntimeError(
        "No LLM configured. Set GOOGLE_API_KEY (Gemini), "
        "OPENROUTER_API_KEY (OpenRouter), or use an ollama: model prefix."
    )


# -----------------------------------------------
# Skill Path Resolution
# -----------------------------------------------
def resolve_skill_paths(skill_ids: list[str] | None = None) -> list[str]:
    """
    Resolve skill directories for DeepAgent's skills parameter.

    If skill_ids are provided, return paths to those specific skill folders.
    Otherwise return the parent skills directory so DeepAgent discovers all.

    DeepAgent expects each path to be a directory containing SKILL.md files.
    """
    base = _resolve_skills_dir()

    if not skill_ids:
        # Return the parent dir — DeepAgent scans subdirectories for SKILL.md
        if os.path.isdir(base):
            return [base + "/"]
        return []

    paths: list[str] = []
    for sid in skill_ids:
        skill_dir = os.path.join(base, sid)
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if os.path.isdir(skill_dir) and os.path.isfile(skill_md):
            paths.append(skill_dir + "/")
        else:
            logger.warning("[DeepAgent] Skill '%s' not found at %s", sid, skill_dir)

    if not paths:
        # Fallback: load all skills
        if os.path.isdir(base):
            logger.info("[DeepAgent] No specific skills found, loading all from %s", base)
            return [base + "/"]

    return paths


# -----------------------------------------------
# Main Agent Execution
# -----------------------------------------------
async def run_deep_agent(
    system_prompt: str,
    user_message: str,
    history: list[dict],
    mcp_tools: list | None = None,
    skill_ids: list[str] | None = None,
    model: str | None = None,
    workspace_dir: str | None = None,
) -> dict[str, Any]:
    """
    Execute a user request using DeepAgents with progressive skill disclosure.

    This is the DROP-IN REPLACEMENT for core.agent_loop.run_agent_loop().

    Architecture (exactly matching the user's reference template):
        1. Create LLM (Gemini primary, OpenRouter/Ollama fallback)
        2. Setup FilesystemBackend with virtual sandboxing
        3. Resolve skill directories (DeepAgent reads SKILL.md frontmatter,
           then uses read_file/execute tools on-demand for scripts & references)
        4. Inject MCP tools (already loaded by caller via mcp_adapter.py)
        5. Execute via create_deep_agent().ainvoke()

    Args:
        system_prompt: Agent's system-level instructions
        user_message: Current user message
        history: Previous conversation messages [{role, content}, ...]
        mcp_tools: Pre-loaded LangChain tools from MCP adapter (optional)
        skill_ids: List of skill IDs to load (optional, loads all if empty)
        model: Override model (e.g. "ollama:qwen3.5:4b", "gemini-3.1-flash")
        workspace_dir: Override workspace directory for sandboxing

    Returns:
        {
            "response": str,           # Final text response
            "tool_calls": list[dict],   # Log of tool calls made
            "model": str,              # Model used
            "iterations": int,         # Number of iterations
        }
    """
    effective_model = model or DEEPAGENT_MODEL
    effective_workspace = workspace_dir or WORKSPACE_DIR

    logger.info(
        "[DeepAgent] Starting agent: model=%s, skills=%s, mcp_tools=%d, workspace=%s",
        effective_model,
        skill_ids or "all",
        len(mcp_tools) if mcp_tools else 0,
        effective_workspace,
    )

    # 1. Create LLM instance
    llm = create_llm(model=effective_model)

    # 2. Resolve skill directories
    skill_paths = resolve_skill_paths(skill_ids)
    logger.info("[DeepAgent] Skill paths: %s", skill_paths)

    # 3. Create the DeepAgent (following user's reference architecture exactly)
    agent_kwargs: dict[str, Any] = {
        "model": llm,
        "backend": FilesystemBackend(
            root_dir=effective_workspace,
            virtual_mode=True,
        ),
        "system_prompt": system_prompt,
    }

    if skill_paths:
        agent_kwargs["skills"] = skill_paths

    if mcp_tools:
        agent_kwargs["tools"] = mcp_tools

    agent = create_deep_agent(**agent_kwargs)

    # 4. Build messages from conversation history
    messages = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "human"):
            messages.append(("user", content))
        elif role in ("assistant", "ai"):
            messages.append(("assistant", content))
        # Skip system/tool messages — system_prompt is already injected

    # Add current user message
    messages.append(("user", user_message))

    # 5. Execute agent
    tool_calls_log: list[dict] = []

    try:
        result = await agent.ainvoke({"messages": messages})

        # Extract final response from DeepAgent output
        final_response = _extract_response(result)

        # Extract tool calls from the execution trace
        tool_calls_log = _extract_tool_calls(result)

        logger.info(
            "[DeepAgent] ✅ Completed: %d chars response, %d tool calls",
            len(final_response),
            len(tool_calls_log),
        )

        return {
            "response": final_response,
            "tool_calls": tool_calls_log,
            "model": effective_model,
            "iterations": len(tool_calls_log) + 1,
        }

    except Exception as e:
        logger.error("[DeepAgent] Execution failed: %s", e, exc_info=True)
        return {
            "response": f"Agent execution error: {str(e)}",
            "tool_calls": tool_calls_log,
            "model": effective_model,
            "iterations": 1,
        }


# -----------------------------------------------
# Streaming variant (for future SSE/WebSocket support)
# -----------------------------------------------
async def stream_deep_agent(
    system_prompt: str,
    user_message: str,
    history: list[dict],
    mcp_tools: list | None = None,
    skill_ids: list[str] | None = None,
    model: str | None = None,
    workspace_dir: str | None = None,
):
    """
    Streaming variant of run_deep_agent. Yields chunks as the agent thinks.
    Useful for real-time UI updates showing agent's thought process.
    """
    effective_model = model or DEEPAGENT_MODEL
    effective_workspace = workspace_dir or WORKSPACE_DIR

    llm = create_llm(model=effective_model)
    skill_paths = resolve_skill_paths(skill_ids)

    agent_kwargs: dict[str, Any] = {
        "model": llm,
        "backend": FilesystemBackend(
            root_dir=effective_workspace,
            virtual_mode=True,
        ),
        "system_prompt": system_prompt,
    }
    if skill_paths:
        agent_kwargs["skills"] = skill_paths
    if mcp_tools:
        agent_kwargs["tools"] = mcp_tools

    agent = create_deep_agent(**agent_kwargs)

    messages = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "human"):
            messages.append(("user", content))
        elif role in ("assistant", "ai"):
            messages.append(("assistant", content))
    messages.append(("user", user_message))

    async for chunk in agent.astream({"messages": messages}):
        yield chunk


# -----------------------------------------------
# Response / Tool-call extraction helpers
# -----------------------------------------------
def _extract_response(result: dict) -> str:
    """Extract the final text response from DeepAgent's output dict."""
    # DeepAgent returns {"messages": [...]} where last AI message is the answer
    messages = result.get("messages", [])
    if not messages:
        return "(Agent returned empty response)"

    # Walk backwards to find the last AI/assistant message with text content
    for msg in reversed(messages):
        content = None
        if hasattr(msg, "content"):
            content = msg.content
        elif isinstance(msg, dict):
            content = msg.get("content")
        elif isinstance(msg, tuple) and len(msg) >= 2:
            if msg[0] in ("assistant", "ai"):
                content = msg[1]

        if content and isinstance(content, str) and content.strip():
            return content.strip()

    return "(Agent returned no text response)"


def _extract_tool_calls(result: dict) -> list[dict]:
    """Extract tool call logs from DeepAgent execution for the chat response."""
    tool_calls: list[dict] = []
    messages = result.get("messages", [])

    for msg in messages:
        # LangChain AIMessage with tool_calls
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "tool": tc.get("name", "unknown"),
                    "args": tc.get("args", {}),
                    "result": "",  # Result comes in ToolMessage
                    "success": True,
                })
        # LangChain ToolMessage (result of a tool call)
        if hasattr(msg, "type") and msg.type == "tool":
            content = msg.content if hasattr(msg, "content") else ""
            if tool_calls:
                # Attach result to the most recent tool call without a result
                for tc in reversed(tool_calls):
                    if not tc["result"]:
                        tc["result"] = str(content)[:500]
                        break

    return tool_calls
