"""
MCP Client - Generic JSON-RPC over Docker stdio
==================================================
Communicates with ANY MCP Docker container via the standard MCP protocol.
Handles: initialize handshake, tools/list, tools/call.

Usage:
    session = MCPContainerSession()
    await session.start("ghcr.io/mark3labs/mcp-filesystem-server:latest", run_config, "/host/path")
    tools = await session.list_tools()
    result = await session.call_tool("read_file", {"path": "/workspace/test.txt"})
    await session.stop()
"""
import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Timeout for MCP operations
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "30"))

# asyncio.StreamReader default readline limit is 64 KiB; large tools/list payloads
# (e.g. mcp-notion) exceed it and raise LimitOverrunError.
MCP_SUBPROCESS_STREAM_LIMIT = int(os.getenv("MCP_SUBPROCESS_STREAM_LIMIT", str(16 * 1024 * 1024)))


def _mask_docker_cmd_for_log(cmd: list[str]) -> str:
    """Redact values after -e KEY=value so secrets are not logged."""
    parts: list[str] = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-e" and i + 1 < len(cmd):
            arg = cmd[i + 1]
            if "=" in arg:
                name, _ = arg.split("=", 1)
                parts.extend(["-e", f"{name}=***"])
            else:
                parts.extend(["-e", arg])
            i += 2
        else:
            parts.append(cmd[i])
            i += 1
    return " ".join(parts)


class MCPError(Exception):
    """Error from MCP server."""
    pass


class MCPContainerSession:
    """
    Manages a single MCP Docker container's lifecycle and JSON-RPC communication.
    
    The container is started via `docker run -i --rm` as a subprocess.
    Communication happens via stdin/stdout using JSON-RPC 2.0 (MCP protocol).
    """

    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None
        self.mcp_name: str = ""
        self.docker_image: str = ""
        self.tools: list[dict] = []
        self.tool_names: set[str] = set()
        self._request_id: int = 0
        self._started: bool = False
        self._initialized: bool = False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def start(
        self,
        docker_image: str,
        run_config: dict,
        workspace_path: str,
        mcp_name: str = "",
    ) -> None:
        """
        Start the MCP container via docker run -i --rm.
        
        Args:
            docker_image: Docker image (e.g. "ghcr.io/mark3labs/mcp-filesystem-server:latest")
            run_config: Run configuration from DB (volumes, env, command, etc.)
            workspace_path: Host path to mount as workspace
            mcp_name: Human-readable name for logging
        """
        self.docker_image = docker_image
        self.mcp_name = mcp_name or docker_image

        cmd = ["docker", "run", "-i", "--rm"]

        # Apply volumes from run_config
        volumes = run_config.get("volumes", {})
        for host_path, container_path in volumes.items():
            # Replace placeholder paths with actual workspace path
            actual_host = host_path.replace("/host/workspace", workspace_path)
            actual_host = actual_host.replace("/host/memory-data", workspace_path + "/.agent-memory")
            cmd.extend(["-v", f"{actual_host}:{container_path}"])

        # Apply environment variables
        environment = run_config.get("environment", {})
        for key, val in environment.items():
            if val and val != "REQUIRED":
                # Check if the value is set in our own env
                actual_val = os.getenv(key, val)
                cmd.extend(["-e", f"{key}={actual_val}"])

        # Add image
        cmd.append(docker_image)

        # Add command arguments
        command_args = run_config.get("command", [])
        if command_args:
            cmd.extend(command_args)

        logger.info(f"[MCP:{self.mcp_name}] Starting: {_mask_docker_cmd_for_log(cmd)}")

        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MCP_SUBPROCESS_STREAM_LIMIT,
            )
            self._started = True
            # Give the container a moment to start
            await asyncio.sleep(1.5)

            # Check if process died immediately
            if self.proc.returncode is not None:
                stderr = await self.proc.stderr.read()
                raise MCPError(
                    f"Container exited immediately (code={self.proc.returncode}): {stderr.decode()[:500]}"
                )

            logger.info(f"[MCP:{self.mcp_name}] Container started (pid={self.proc.pid})")
        except FileNotFoundError:
            raise MCPError("Docker CLI not found. Ensure docker is installed in the container.")
        except Exception as e:
            raise MCPError(f"Failed to start MCP container: {e}")

    async def initialize(self) -> dict:
        """Send the MCP initialize handshake."""
        if not self._started:
            raise MCPError("Container not started")

        # Step 1: Send initialize request
        init_response = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "agent-builder-v5",
                "version": "1.0.0",
            },
        })

        # Step 2: Send initialized notification (no response expected)
        await self._send_notification("notifications/initialized")

        self._initialized = True
        server_info = init_response.get("result", {}).get("serverInfo", {})
        logger.info(
            f"[MCP:{self.mcp_name}] Initialized: {server_info.get('name', 'unknown')} "
            f"v{server_info.get('version', '?')}"
        )
        return init_response

    async def list_tools(self) -> list[dict]:
        """
        Get the list of available tools from the MCP server.
        Returns tools in MCP format: [{name, description, inputSchema}, ...]
        """
        if not self._initialized:
            await self.initialize()

        response = await self._send_request("tools/list")
        tools = response.get("result", {}).get("tools", [])

        self.tools = tools
        self.tool_names = {t["name"] for t in tools}

        logger.info(f"[MCP:{self.mcp_name}] Available tools: {list(self.tool_names)}")
        return tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """
        Call a tool on the MCP server and return the result as a string.
        
        Args:
            name: Tool name (e.g. "read_file")
            arguments: Tool arguments dict

        Returns:
            Tool result as a string
        """
        if not self._initialized:
            raise MCPError("Session not initialized")

        logger.info(f"[MCP:{self.mcp_name}] Calling tool: {name}({json.dumps(arguments)[:200]})")

        response = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        result = response.get("result", {})

        # MCP tool results come as content array: [{type: "text", text: "..."}, ...]
        content = result.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    elif item.get("type") == "image":
                        texts.append(f"[Image: {item.get('mimeType', 'image')}]")
                    else:
                        texts.append(str(item))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        
        return str(content)

    async def stop(self) -> None:
        """Kill the container process."""
        if self.proc and self.proc.returncode is None:
            logger.info(f"[MCP:{self.mcp_name}] Stopping container...")
            try:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            except Exception as e:
                logger.warning(f"[MCP:{self.mcp_name}] Error stopping: {e}")
        self._started = False
        self._initialized = False

    # -----------------------------------------------
    # Internal JSON-RPC communication
    # -----------------------------------------------

    async def _send_request(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request and wait for response."""
        req_id = self._next_id()
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params

        await self._write(message)
        response = await self._read_response(req_id)

        if "error" in response:
            err = response["error"]
            raise MCPError(f"MCP error ({err.get('code', '?')}): {err.get('message', 'Unknown error')}")

        return response

    async def _send_notification(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params

        await self._write(message)
        # Small delay to let server process
        await asyncio.sleep(0.1)

    async def _write(self, message: dict) -> None:
        """Write a JSON-RPC message to the container's stdin."""
        if not self.proc or not self.proc.stdin:
            raise MCPError("No connection to MCP container")

        data = json.dumps(message) + "\n"
        self.proc.stdin.write(data.encode())
        await self.proc.stdin.drain()
        logger.debug(f"[MCP:{self.mcp_name}] → {data.strip()[:200]}")

    async def _read_response(self, expected_id: int) -> dict:
        """Read a JSON-RPC response with the expected id."""
        if not self.proc or not self.proc.stdout:
            raise MCPError("No connection to MCP container")

        try:
            # Read lines until we get the response with our id
            # (skip notifications the server might send)
            for _ in range(50):  # Max attempts to find our response
                line = await asyncio.wait_for(
                    self.proc.stdout.readline(),
                    timeout=MCP_TIMEOUT,
                )
                
                if not line:
                    # Check if process died
                    if self.proc.returncode is not None:
                        stderr_data = await self.proc.stderr.read()
                        raise MCPError(
                            f"MCP container died: {stderr_data.decode()[:500]}"
                        )
                    continue

                line_str = line.decode().strip()
                if not line_str:
                    continue

                logger.debug(f"[MCP:{self.mcp_name}] ← {line_str[:200]}")

                try:
                    response = json.loads(line_str)
                except json.JSONDecodeError:
                    logger.warning(f"[MCP:{self.mcp_name}] Non-JSON output: {line_str[:100]}")
                    continue

                # Check if this is our response (has matching id)
                if response.get("id") == expected_id:
                    return response

                # If it's a notification (no id), log and continue
                if "id" not in response:
                    logger.debug(f"[MCP:{self.mcp_name}] Server notification: {response.get('method', '?')}")
                    continue

            raise MCPError(f"No response received for request id={expected_id}")

        except asyncio.TimeoutError:
            raise MCPError(f"Timeout waiting for MCP response (>{MCP_TIMEOUT}s)")


def mcp_tools_to_openrouter(mcp_tools: list[dict]) -> list[dict]:
    """
    Convert MCP tool definitions to OpenRouter/OpenAI function calling format.
    
    MCP format:
        {name, description, inputSchema: {type: "object", properties: {...}}}
    
    OpenRouter format:
        {type: "function", function: {name, description, parameters: {...}}}
    """
    openrouter_tools = []
    for tool in mcp_tools:
        openrouter_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
            },
        })
    return openrouter_tools
