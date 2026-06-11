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

logger = logging.getLogger(__name__)


def _ensure_nest_asyncio():
    """Apply nest_asyncio only when needed and only if the loop supports it."""
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except (ValueError, RuntimeError):
        # uvloop (used by uvicorn) doesn't support patching — skip silently
        pass


# Lazy imports — deepagents is only installed in the agent-engine container
_create_deep_agent = None
_FilesystemBackend = None


def _lazy_imports():
    """Import deepagents lazily so the API container doesn't crash on import."""
    global _create_deep_agent, _FilesystemBackend
    if _create_deep_agent is None:
        _ensure_nest_asyncio()
        from deepagents import create_deep_agent
        from deepagents.backends import FilesystemBackend
        _create_deep_agent = create_deep_agent
        _FilesystemBackend = FilesystemBackend

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


def _build_strict_system_prompt(base_prompt: str, mcp_tools: list | None = None) -> str:
    """Inject anti-hallucination and networking instructions into the system prompt."""
    tool_names = [t.name for t in mcp_tools] if mcp_tools else []
    tool_examples = f" (e.g., '{tool_names[0]}')" if tool_names else ""

    return base_prompt + (
        "\n\nCRITICAL TOOL USAGE INSTRUCTIONS:\n"
        "1. You MUST ONLY use the tools explicitly provided to you in your tools list.\n"
        "2. NEVER use or attempt to call tools that are not explicitly provided (e.g., do NOT use 'google:search', 'search', or 'web_search' unless explicitly in your tools list).\n"
        f"3. Always use the exact tool name provided{tool_examples}.\n"
        "\nNETWORKING NOTE:\n"
        "Your tools run inside Docker containers. 'localhost' inside a container refers to the container itself, NOT the host machine.\n"
        "- When a user gives you a URL with 'localhost', ALWAYS replace it with 'host.docker.internal' before passing to tools.\n"
        "  Example: http://localhost:3001/ becomes http://host.docker.internal:3001/\n"
        "- This applies to ALL tools: curl, nmap, nuclei, gobuster, etc.\n"
        "\nANTI-LOOP RULES:\n"
        "- NEVER call the same tool with the same arguments more than 2 times. If a tool returns an error or truncated data, summarize what you have and move on.\n"
        "- If a result says 'truncated' or refers to a 'resource_uri', just summarize the partial data you received \u2014 do NOT try to fetch the full version repeatedly.\n"
        "- If fetch_file returns 'File not found', do NOT retry. Summarize available data and continue.\n"
    )


# -----------------------------------------------
# LLM Factory — Gemini primary, OpenRouter/Ollama fallback
# -----------------------------------------------
def _is_openrouter_model(model: str) -> bool:
    """
    Return True if the model string looks like an OpenRouter model ID
    (e.g. "meta-llama/llama-3.1-8b-instruct:free").
    OpenRouter IDs always contain "/" and are NOT native Gemini/Ollama model names.
    """
    if model.startswith("gemini") or model.startswith("models/gemini"):
        return False
    if model.startswith("ollama:") or model.startswith("ollama_remote:"):
        return False
    return "/" in model


# Canonical safe fallback models per provider
_GEMINI_SAFE_MODEL = os.getenv("DEEPAGENT_MODEL", "gemini-2.0-flash-lite")
_OPENROUTER_SAFE_MODEL = "meta-llama/llama-3.1-8b-instruct:free"


def create_llm(model: str | None = None, temperature: float | None = None):
    """
    Create a LangChain-compatible LLM instance.

    Routing priority:
        1. "ollama:tag"  → Ollama (local or remote)
        2. GOOGLE_API_KEY present AND model is NOT an OpenRouter-style ID
           → ChatGoogleGenerativeAI (Gemini).  If model looks like an OpenRouter
             name (contains "/"), we silently substitute DEEPAGENT_MODEL so we
             never feed an OpenRouter slug to the Gemini API.
        3. OPENROUTER_API_KEY present → ChatOpenAI → OpenRouter
        4. Neither → RuntimeError
    """
    effective_model = model or DEEPAGENT_MODEL
    effective_temp = temperature if temperature is not None else DEEPAGENT_TEMPERATURE

    # ── Ollama (remote) route ─────────────────────────────────────────────────
    if effective_model.startswith("ollama_remote:"):
        from langchain_openai import ChatOpenAI

        ollama_tag = effective_model.split(":", 1)[1]
        remote_base = os.getenv("OLLAMA_REMOTE_BASE_URL", "").strip().rstrip("/")
        if not remote_base:
            raise RuntimeError(
                "OLLAMA_REMOTE_BASE_URL is not set. "
                "Add it to .env: OLLAMA_REMOTE_BASE_URL=https://your-ngrok-url"
            )
        api_key = os.getenv("OLLAMA_REMOTE_API_KEY", "ollama")
        logger.info("[DeepAgent] Using Ollama remote: %s @ %s", ollama_tag, remote_base)
        return ChatOpenAI(
            model=ollama_tag,
            base_url=f"{remote_base}/v1",
            api_key=api_key,
            temperature=effective_temp,
            default_headers={"ngrok-skip-browser-warning": "1"},
        )

    # ── Ollama (local) route ──────────────────────────────────────────────────
    if effective_model.startswith("ollama:"):
        from langchain_openai import ChatOpenAI

        ollama_tag = effective_model.split(":", 1)[1]
        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        logger.info("[DeepAgent] Using Ollama local: %s @ %s", ollama_tag, ollama_base)
        return ChatOpenAI(
            model=ollama_tag,
            base_url=f"{ollama_base}/v1",
            api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
            temperature=effective_temp,
        )

    # ── Gemini route (primary) ────────────────────────────────────────────────
    if GOOGLE_API_KEY:
        from langchain_google_genai import ChatGoogleGenerativeAI

        # If the stored model is an OpenRouter slug (e.g. "anthropic/claude-3.5-sonnet"),
        # it's invalid for the Gemini API — fall back to our default Gemini model.
        if _is_openrouter_model(effective_model):
            logger.warning(
                "[DeepAgent] Model '%s' looks like an OpenRouter slug — substituting '%s' for Gemini",
                effective_model,
                _GEMINI_SAFE_MODEL,
            )
            effective_model = _GEMINI_SAFE_MODEL

        logger.info("[DeepAgent] Using Gemini: %s", effective_model)
        return ChatGoogleGenerativeAI(
            model=effective_model,
            temperature=effective_temp,
            google_api_key=GOOGLE_API_KEY,
        )

    # ── OpenRouter fallback ──────────────────────────────────────────────────
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        from langchain_openai import ChatOpenAI

        openrouter_base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        # Sanitize: if the model is not an OpenRouter-style slug, swap to a known safe one
        if not _is_openrouter_model(effective_model) and not effective_model.startswith("ollama:"):
            logger.warning(
                "[DeepAgent] Model '%s' not an OpenRouter slug — substituting '%s'",
                effective_model,
                _OPENROUTER_SAFE_MODEL,
            )
            effective_model = _OPENROUTER_SAFE_MODEL

        logger.info("[DeepAgent] Using OpenRouter: %s", effective_model)
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
    images: list[dict] | None = None,
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
    _lazy_imports()

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

    # Inject strong anti-hallucination instructions to prevent R1/Ollama models from making up tools
    strict_system_prompt = _build_strict_system_prompt(system_prompt, mcp_tools)

    # 3. Create the DeepAgent (following user's reference architecture exactly)
    agent_kwargs: dict[str, Any] = {
        "model": llm,
        "backend": _FilesystemBackend(
            root_dir=effective_workspace,
            virtual_mode=True,
        ),
        "system_prompt": strict_system_prompt,
    }

    if skill_paths:
        agent_kwargs["skills"] = skill_paths

    if mcp_tools:
        agent_kwargs["tools"] = mcp_tools

    agent = _create_deep_agent(**agent_kwargs)

    # 4. Build messages from conversation history
    messages = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "human"):
            # content may be a multimodal list (previous vision turns)
            if isinstance(content, list):
                messages.append(("user", content))
            else:
                messages.append(("user", content))
        elif role in ("assistant", "ai"):
            messages.append(("assistant", content if isinstance(content, str) else str(content)))
        # Skip system/tool messages — system_prompt is already injected

    # Add current user message (multimodal if images attached)
    if images:
        multimodal_content: list = [{"type": "text", "text": user_message}]
        for img in images:
            multimodal_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.get('media_type', 'image/jpeg')};base64,{img['data']}",
                },
            })
        messages.append(("user", multimodal_content))
    else:
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
    _lazy_imports()

    effective_model = model or DEEPAGENT_MODEL
    effective_workspace = workspace_dir or WORKSPACE_DIR

    llm = create_llm(model=effective_model)
    skill_paths = resolve_skill_paths(skill_ids)

    strict_system_prompt = _build_strict_system_prompt(system_prompt, mcp_tools)

    agent_kwargs: dict[str, Any] = {
        "model": llm,
        "backend": _FilesystemBackend(
            root_dir=effective_workspace,
            virtual_mode=True,
        ),
        "system_prompt": strict_system_prompt,
    }
    if skill_paths:
        agent_kwargs["skills"] = skill_paths
    if mcp_tools:
        agent_kwargs["tools"] = mcp_tools

    agent = _create_deep_agent(**agent_kwargs)

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
        
        # 1. LangChain BaseMessage objects
        if hasattr(msg, "type"):
            if msg.type in ("ai", "assistant"):
                content = msg.content if hasattr(msg, "content") else None
                
        # 2. Raw dicts
        elif isinstance(msg, dict):
            if msg.get("role") in ("assistant", "ai") or msg.get("type") in ("ai", "assistant"):
                content = msg.get("content")
                
        # 3. Tuples (role, content)
        elif isinstance(msg, tuple) and len(msg) >= 2:
            if msg[0] in ("assistant", "ai"):
                content = msg[1]

        if content:
            if isinstance(content, str) and content.strip():
                return content.strip()
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                extracted = "\n".join(text_parts).strip()
                if extracted:
                    return extracted

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
