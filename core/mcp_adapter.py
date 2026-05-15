"""
MCP Adapter — LangChain-native MCP tool loading
==================================================
Replaces the custom JSON-RPC stdio client (core/mcp_client.py) with
langchain_mcp_adapters for native DeepAgent integration.

Supports:
    - HTTP (Streamable HTTP) transport — recommended for Docker containers
    - SSE (Server-Sent Events) transport — legacy but still supported
    - stdio transport — via subprocess (fallback for containers without HTTP)

Usage:
    tools = await load_mcp_tools_for_agent(mcp_configs)
    agent = create_deep_agent(model=llm, tools=tools, ...)
"""
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _coerce_args(args: dict) -> dict:
    """
    Sanitize Windows-MCP tool args that LLMs commonly malform:
      - label : expected int  → coerce string-digit to int, otherwise drop (None)
      - loc   : expected [x,y] list of ints  → drop unless it's already a 2-int list
    """
    args = dict(args)

    if "label" in args:
        v = args["label"]
        if isinstance(v, str):
            s = v.strip()
            args["label"] = int(s) if s.lstrip("-").isdigit() else None
        elif not isinstance(v, (int, type(None))):
            args["label"] = None

    if "loc" in args:
        v = args["loc"]
        if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
            args["loc"] = [int(v[0]), int(v[1])]
        elif isinstance(v, (tuple,)) and len(v) == 2:
            args["loc"] = [int(v[0]), int(v[1])]
        elif v is None:
            pass
        else:
            args["loc"] = None

    return args


def _coerce_label(tool_input: Any) -> Any:
    """
    Sanitize a tool input (dict or ToolCall) before pydantic validation.
    Handles both direct dict inputs and ToolCall format: {'name':..., 'args':{...}}.
    """
    if not isinstance(tool_input, dict):
        return tool_input

    # ToolCall format: {'name': 'Type', 'args': {...}, ...}
    if "args" in tool_input and isinstance(tool_input.get("args"), dict):
        return {**tool_input, "args": _coerce_args(tool_input["args"])}

    # Direct dict format: {'text': '...', 'label': '...', 'loc': ...}
    if any(k in tool_input for k in ("label", "loc")):
        return _coerce_args(tool_input)

    return tool_input


MAX_TOOL_OUTPUT_CHARS = int(os.getenv("MCP_MAX_TOOL_OUTPUT_CHARS", "8000"))


def _truncate_result(result: Any) -> Any:
    """
    Truncate huge tool results (e.g. Windows-MCP Snapshot) so they don't blow up
    the LLM context. Keeps the head + tail with a marker in between.
    """
    try:
        if hasattr(result, "content"):
            content = result.content
            if isinstance(content, str) and len(content) > MAX_TOOL_OUTPUT_CHARS:
                half = MAX_TOOL_OUTPUT_CHARS // 2
                truncated = (
                    content[:half]
                    + f"\n\n... [TRUNCATED {len(content) - MAX_TOOL_OUTPUT_CHARS} chars] ...\n\n"
                    + content[-half:]
                )
                try:
                    object.__setattr__(result, "content", truncated)
                except Exception:
                    pass
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        text = item["text"]
                        if len(text) > MAX_TOOL_OUTPUT_CHARS:
                            half = MAX_TOOL_OUTPUT_CHARS // 2
                            item["text"] = (
                                text[:half]
                                + f"\n\n... [TRUNCATED {len(text) - MAX_TOOL_OUTPUT_CHARS} chars] ...\n\n"
                                + text[-half:]
                            )
    except Exception as exc:
        logger.debug("[MCPAdapter] Truncation skipped: %s", exc)
    return result


def _patch_label_schema(tools: list) -> list:
    """
    Patches Windows-MCP tools in two ways:
      1) ainvoke() coerces malformed `label` (string→int|None) and `loc` (dict→None)
         arguments BEFORE pydantic validation — so the LLM's mistakes don't crash.
      2) Wraps ainvoke to truncate huge results (e.g. Snapshot returns 19KB+ text)
         so they don't overflow the LLM context window.
    Uses object.__setattr__ to bypass Pydantic's __setattr__ guard.
    """
    patched_names = []
    for tool in tools:
        schema = getattr(tool, "args_schema", None)

        if isinstance(schema, dict):
            props = schema.get("properties", {})
            needs_coerce = "label" in props or "loc" in props
        else:
            fields = getattr(schema, "model_fields", {})
            needs_coerce = "label" in fields or "loc" in fields

        original_ainvoke = tool.ainvoke  # bound method — captures self

        def _make_patched_ainvoke(orig, do_coerce: bool):
            async def _patched_ainvoke(input_: Any, config: Any = None, **kwargs: Any) -> Any:
                if do_coerce:
                    input_ = _coerce_label(input_)
                result = await orig(input_, config, **kwargs)
                return _truncate_result(result)
            return _patched_ainvoke

        try:
            object.__setattr__(tool, "ainvoke", _make_patched_ainvoke(original_ainvoke, needs_coerce))
            if needs_coerce:
                patched_names.append(tool.name)
        except Exception as exc:
            logger.warning("[MCPAdapter] Could not patch %s: %s", tool.name, exc)

    if patched_names:
        logger.info("[MCPAdapter] coerce+truncate patched on: %s", patched_names)
    else:
        logger.info("[MCPAdapter] truncate wrapper applied to all %d tools", len(tools))

    return tools


async def load_mcp_tools_for_agent(
    mcp_configs: list[dict],
    mcp_user_configs: dict[str, dict] | None = None,
) -> list:
    """
    Load LangChain-compatible tools from MCP Docker containers.

    Converts the build template's MCP config list into live LangChain tools
    using langchain_mcp_adapters.MultiServerMCPClient.

    Args:
        mcp_configs: List of MCP configs from the agent template, each with:
            - mcp_name: str
            - docker_image: str
            - run_config: dict (may contain transport, ports)
            - running_port: int | None
            - transport: "http" | "sse" | "stdio"
        mcp_user_configs: Optional user-provided API keys per MCP

    Returns:
        List of LangChain tool objects ready for create_deep_agent(tools=...)
    """
    if not mcp_configs:
        return []

    server_configs = {}

    for mcp in mcp_configs:
        name = mcp.get("mcp_name", "")
        if not name:
            continue

        run_config = mcp.get("run_config", {}) or {}
        # transport can be top-level on the mcp dict (runtime override)
        # or stored inside run_config (DB default) — run_config wins for external MCPs
        transport = mcp.get("transport") or run_config.get("transport", "stdio")
        port = mcp.get("running_port")

        # Build connection config based on transport type
        direct_url = run_config.get("url", "")

        if transport == "http" and direct_url:
            # External HTTP MCP (not Docker-managed) — use URL as-is
            server_configs[name] = {
                "transport": "streamable_http",
                "url": direct_url,
            }
        elif transport == "sse" and direct_url:
            # External SSE MCP (e.g. Windows-MCP running on host machine)
            server_configs[name] = {
                "transport": "sse",
                "url": direct_url,
            }
        elif transport == "http" and port:
            server_configs[name] = {
                "transport": "streamable_http",
                "url": f"http://localhost:{port}/mcp",
            }
        elif transport == "sse" and port:
            server_configs[name] = {
                "transport": "sse",
                "url": f"http://localhost:{port}/sse",
            }
        elif transport == "stdio":
            # For stdio containers, we need docker_image and command
            docker_image = mcp.get("docker_image", "")
            if not docker_image:
                logger.warning("[MCPAdapter] Skipping %s: no docker_image for stdio", name)
                continue

            cmd = ["docker", "run", "-i", "--rm"]

            # Add volumes
            workspace = os.getenv("WORKSPACE_PATH", "/workspace")
            volumes = run_config.get("volumes", {})
            for host_path, container_path in volumes.items():
                actual = host_path.replace("/host/workspace", workspace)
                cmd.extend(["-v", f"{actual}:{container_path}"])

            # Add environment and dynamic volumes
            env = dict(run_config.get("environment", {}))
            command_args = list(run_config.get("command", []))
            
            if mcp_user_configs and name in mcp_user_configs:
                user_cfg = mcp_user_configs[name]
                env.update(user_cfg)
                
                # Check if this MCP configures a specific directory (like mcp-filesystem)
                if "allowed_directory" in user_cfg and user_cfg["allowed_directory"].strip():
                    host_dir = user_cfg["allowed_directory"].strip()
                    # Mount the user-provided host path to /user_dir in the container
                    cmd.extend(["-v", f"{host_dir}:/user_dir"])
                    
                    # For mcp-filesystem, we append /user_dir to the allowed paths
                    if "/user_dir" not in command_args:
                        command_args.append("/user_dir")

            for key, val in env.items():
                if val and val != "REQUIRED" and key != "allowed_directory":
                    actual_val = os.getenv(key, val)
                    cmd.extend(["-e", f"{key}={actual_val}"])

            cmd.append(docker_image)
            if command_args:
                cmd.extend(command_args)

            server_configs[name] = {
                "transport": "stdio",
                "command": cmd[0],
                "args": cmd[1:],
            }

        else:
            logger.warning(
                "[MCPAdapter] Skipping %s: transport=%s, port=%s — unsupported combo",
                name, transport, port,
            )

    if not server_configs:
        logger.info("[MCPAdapter] No MCP servers to connect to")
        return []

    # Load tools via MultiServerMCPClient
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        logger.info(
            "[MCPAdapter] Connecting to %d MCP server(s): %s",
            len(server_configs),
            list(server_configs.keys()),
        )

        client = MultiServerMCPClient(server_configs)
        tools = await client.get_tools()
        tools = _patch_label_schema(tools)
        logger.info("[MCPAdapter] ✅ Loaded %d tools from MCP servers", len(tools))
        return tools

    except Exception as e:
        logger.error("[MCPAdapter] Failed to load MCP tools: %s", e, exc_info=True)
        return []


async def load_mcp_tools_persistent(
    mcp_configs: list[dict],
    mcp_user_configs: dict[str, dict] | None = None,
) -> tuple[Any, list]:
    """
    Like load_mcp_tools_for_agent but returns the client handle too,
    so the caller can keep the connection alive for the session duration.

    Returns:
        (client, tools) — caller must close client when done.
    """
    if not mcp_configs:
        return None, []

    server_configs = {}
    for mcp in mcp_configs:
        name = mcp.get("mcp_name", "")
        run_config = mcp.get("run_config", {}) or {}
        transport = mcp.get("transport") or run_config.get("transport", "stdio")
        port = mcp.get("running_port")
        direct_url = run_config.get("url", "")

        if transport in ("http", "sse") and direct_url:
            server_configs[name] = {
                "transport": "streamable_http" if transport == "http" else "sse",
                "url": direct_url,
            }
        elif transport in ("http", "sse") and port:
            server_configs[name] = {
                "transport": "streamable_http" if transport == "http" else "sse",
                "url": f"http://localhost:{port}/{'mcp' if transport == 'http' else 'sse'}",
            }

    if not server_configs:
        return None, []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(server_configs)
        tools = await client.get_tools()
        logger.info("[MCPAdapter] Persistent connection: %d tools", len(tools))
        return client, tools
    except Exception as e:
        logger.error("[MCPAdapter] Persistent connection failed: %s", e)
        return None, []
