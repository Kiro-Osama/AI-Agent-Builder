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
from typing import Any

logger = logging.getLogger(__name__)


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

        transport = mcp.get("transport", "stdio")
        port = mcp.get("running_port")
        run_config = mcp.get("run_config", {}) or {}

        # Build connection config based on transport type
        if transport == "http" and port:
            server_configs[name] = {
                "transport": "http",
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

            # Add environment
            env = dict(run_config.get("environment", {}))
            if mcp_user_configs and name in mcp_user_configs:
                env.update(mcp_user_configs[name])
            for key, val in env.items():
                if val and val != "REQUIRED":
                    actual_val = os.getenv(key, val)
                    cmd.extend(["-e", f"{key}={actual_val}"])

            cmd.append(docker_image)
            command_args = run_config.get("command", [])
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
        transport = mcp.get("transport", "stdio")
        port = mcp.get("running_port")

        if transport in ("http", "sse") and port:
            server_configs[name] = {
                "transport": transport,
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
