"""
Agent Session Manager
======================
Manages MCP container sessions for a chat conversation.
Handles starting multiple MCPs, aggregating tools, routing tool calls.
"""
import asyncio
import logging
import os
from typing import Any

from core.mcp_client import MCPContainerSession, MCPError

logger = logging.getLogger(__name__)

WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", "/workspace")


class AgentSession:
    """
    Holds running MCP containers + aggregated tools for one chat session.
    
    Lifecycle:
        1. start(selected_mcps) → starts all MCP containers, discovers tools
        2. call_tool(name, args) → routes to correct container
        3. cleanup() → stops all containers
    """

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.containers: list[MCPContainerSession] = []
        self.all_tools: list[dict] = []  # MCP-format tools from all containers
        self.tool_to_container: dict[str, MCPContainerSession] = {}
        self.active: bool = False
        self.errors: list[str] = []

    async def start(self, selected_mcps: list[dict]) -> list[dict]:
        """
        Start MCP containers and discover all available tools.
        
        Args:
            selected_mcps: List of MCP configs from the build template.
                Each has: mcp_name, docker_image, run_config, tools_provided
        
        Returns:
            Aggregated list of all available tools (MCP format)
        """
        if not selected_mcps:
            logger.info(f"[Session:{self.session_id}] No MCPs to start")
            self.active = True
            return []

        workspace = WORKSPACE_PATH
        logger.info(
            f"[Session:{self.session_id}] Starting {len(selected_mcps)} MCP(s), "
            f"workspace={workspace}"
        )

        for mcp_config in selected_mcps:
            mcp_name = mcp_config.get("mcp_name", "unknown")
            docker_image = mcp_config.get("docker_image", "")
            run_config = mcp_config.get("run_config", {}) or {}

            if not docker_image:
                self.errors.append(f"{mcp_name}: no docker_image specified")
                continue

            container = MCPContainerSession()
            try:
                # Start the container
                await container.start(
                    docker_image=docker_image,
                    run_config=run_config,
                    workspace_path=workspace,
                    mcp_name=mcp_name,
                )

                # Initialize MCP protocol
                await container.initialize()

                # Discover tools
                tools = await container.list_tools()

                # Register tools
                for tool in tools:
                    tool_name = tool["name"]
                    # Prefix with MCP name if there's a conflict
                    if tool_name in self.tool_to_container:
                        prefixed = f"{mcp_name}__{tool_name}"
                        logger.warning(
                            f"[Session:{self.session_id}] Tool name conflict: {tool_name}, "
                            f"prefixing as {prefixed}"
                        )
                        tool["name"] = prefixed
                        tool_name = prefixed

                    self.tool_to_container[tool_name] = container
                    self.all_tools.append(tool)

                self.containers.append(container)
                logger.info(
                    f"[Session:{self.session_id}] ✅ {mcp_name}: {len(tools)} tools ready"
                )

            except MCPError as e:
                error_msg = f"{mcp_name}: {e}"
                self.errors.append(error_msg)
                logger.error(f"[Session:{self.session_id}] ❌ {error_msg}")
                # Clean up failed container
                await container.stop()

            except Exception as e:
                error_msg = f"{mcp_name}: unexpected error: {e}"
                self.errors.append(error_msg)
                logger.error(f"[Session:{self.session_id}] ❌ {error_msg}")
                await container.stop()

        self.active = True
        logger.info(
            f"[Session:{self.session_id}] Session ready: "
            f"{len(self.containers)} MCPs, {len(self.all_tools)} tools"
        )

        if self.errors:
            logger.warning(
                f"[Session:{self.session_id}] Errors: {self.errors}"
            )

        return self.all_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Route a tool call to the correct MCP container.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result as string
        """
        container = self.tool_to_container.get(tool_name)
        if not container:
            available = list(self.tool_to_container.keys())
            return f"Error: Tool '{tool_name}' not found. Available: {available}"

        try:
            result = await container.call_tool(tool_name, arguments)
            return result
        except MCPError as e:
            logger.error(f"[Session:{self.session_id}] Tool error {tool_name}: {e}")
            return f"Error executing {tool_name}: {e}"
        except Exception as e:
            logger.error(f"[Session:{self.session_id}] Unexpected tool error {tool_name}: {e}")
            return f"Unexpected error in {tool_name}: {e}"

    def get_tool_names(self) -> list[str]:
        """Get list of all available tool names."""
        return list(self.tool_to_container.keys())

    def get_mcp_summary(self) -> str:
        """Get a human-readable summary of connected MCPs and tools."""
        lines = []
        for container in self.containers:
            tools_str = ", ".join(container.tool_names)
            lines.append(f"- {container.mcp_name}: [{tools_str}]")
        return "\n".join(lines) if lines else "No MCPs connected"

    async def cleanup(self) -> None:
        """Stop all MCP containers."""
        if not self.containers:
            return

        logger.info(
            f"[Session:{self.session_id}] Cleaning up {len(self.containers)} MCP(s)..."
        )
        
        # Stop all containers concurrently
        await asyncio.gather(
            *[c.stop() for c in self.containers],
            return_exceptions=True,
        )
        
        self.containers.clear()
        self.all_tools.clear()
        self.tool_to_container.clear()
        self.active = False
        logger.info(f"[Session:{self.session_id}] Cleanup done")


# -----------------------------------------------
# Session Store (in-memory, keyed by conversation_id)
# -----------------------------------------------
_sessions: dict[str, AgentSession] = {}


def get_session(conversation_id: str) -> AgentSession | None:
    """Get an existing session."""
    return _sessions.get(conversation_id)


def create_session(conversation_id: str) -> AgentSession:
    """Create and register a new session."""
    session = AgentSession(session_id=conversation_id)
    _sessions[conversation_id] = session
    return session


async def cleanup_session(conversation_id: str) -> None:
    """Cleanup and remove a session."""
    session = _sessions.pop(conversation_id, None)
    if session:
        await session.cleanup()


async def cleanup_all_sessions() -> None:
    """Cleanup all active sessions (called on shutdown)."""
    for conv_id in list(_sessions.keys()):
        await cleanup_session(conv_id)
