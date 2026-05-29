"""
MCP Container Manager
=======================
Manages persistent MCP Docker containers that stay alive between requests.

Instead of: docker run --rm -i image  (dies after each tool call)
We do:       docker run -d -p PORT:PORT image  (runs in background forever)

The containers are tracked by (image, args) key and reused across sessions.
"""
import asyncio
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

# In-memory registry: key -> {"container_id": str, "port": int, "url": str}
_persistent_containers: dict[str, dict] = {}
_lock = asyncio.Lock()


def _find_free_port(start: int = 14000, end: int = 14100) -> int:
    """Find an available port in range."""
    import socket
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(("localhost", port)) != 0:
                return port
    raise RuntimeError("No free ports available in range")


def _container_alive(container_id: str) -> bool:
    """Check if a container is still running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


def _wait_for_http(url: str, timeout: int = 30) -> bool:
    """Wait until an HTTP endpoint responds."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


async def get_or_start_persistent_container(
    docker_image: str,
    run_config: dict,
    mcp_name: str,
    mcp_user_configs: dict | None = None,
) -> dict | None:
    """
    Get or start a persistent MCP container in HTTP mode.

    Returns:
        {"url": "http://localhost:PORT/mcp", "transport": "streamable_http"}
        or None if failed.
    """
    # Build a stable key for this MCP configuration
    cache_key = f"{mcp_name}:{docker_image}"

    async with _lock:
        # Check if we already have a running container
        existing = _persistent_containers.get(cache_key)
        if existing:
            if _container_alive(existing["container_id"]):
                logger.info("[MCPContainerMgr] Reusing container %s for %s at %s",
                            existing["container_id"][:12], mcp_name, existing["url"])
                return {"url": existing["url"], "transport": "streamable_http"}
            else:
                logger.info("[MCPContainerMgr] Container died, restarting: %s", mcp_name)
                _persistent_containers.pop(cache_key, None)

        # Start a new persistent container
        port = _find_free_port()
        cmd = ["docker", "run", "-d",          # detached — runs in background
               "--name", f"mcp-{mcp_name}-{port}",
               "--restart", "unless-stopped",  # auto-restart on crash
               "-p", f"{port}:{port}"]

        # Add network so it can reach host
        cmd.extend(["--add-host", "host.docker.internal:host-gateway"])

        # Add volumes from run_config
        workspace = os.getenv("WORKSPACE_PATH", "/workspace")
        volumes = run_config.get("volumes", {})
        for host_path, container_path in volumes.items():
            actual = host_path.replace("/host/workspace", workspace)
            cmd.extend(["-v", f"{actual}:{container_path}"])

        # Add volumes directory for pentest-mcp output
        output_dir = run_config.get("output_dir", "")
        if output_dir:
            cmd.extend(["-v", f"{output_dir}:{output_dir}"])

        # Env vars
        env = dict(run_config.get("environment", {}))
        if mcp_user_configs and mcp_name in (mcp_user_configs or {}):
            user_cfg = mcp_user_configs[mcp_name]
            env.update(user_cfg)
            if "allowed_directory" in user_cfg and user_cfg["allowed_directory"].strip():
                host_dir = user_cfg["allowed_directory"].strip()
                cmd.extend(["-v", f"{host_dir}:/user_dir"])

        for key, val in env.items():
            if val and val != "REQUIRED" and key != "allowed_directory":
                actual_val = os.getenv(key, str(val))
                cmd.extend(["-e", f"{key}={actual_val}"])

        cmd.append(docker_image)

        # Determine HTTP startup command
        # pentest-mcp supports --transport http --port PORT
        if "ramgameer/pentest-mcp" in docker_image:
            cmd.extend(["python3", "/opt/pentest-mcp/pentestMCP.py",
                        "--transport", "http", "--port", str(port)])
        else:
            # Try generic --transport http --port PORT pattern
            command_args = run_config.get("command", [])
            if command_args:
                cmd.extend(command_args)
            # Replace stdio args with http if present
            if "--transport" not in str(cmd):
                cmd.extend(["--transport", "http", "--port", str(port)])

        logger.info("[MCPContainerMgr] Starting persistent container: %s", " ".join(cmd))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error("[MCPContainerMgr] Failed to start %s: %s", mcp_name, result.stderr)
                return None
            container_id = result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("[MCPContainerMgr] Timeout starting container for %s", mcp_name)
            return None
        except Exception as e:
            logger.error("[MCPContainerMgr] Error starting container: %s", e)
            return None

        url = f"http://host.docker.internal:{port}/mcp"

        logger.info("[MCPContainerMgr] Waiting for %s to be ready at %s ...", mcp_name, url)

        # Wait for the container HTTP server to be ready
        ready = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _wait_for_http(url, timeout=30)
        )

        if not ready:
            logger.error("[MCPContainerMgr] %s did not come up in time, killing %s", mcp_name, container_id[:12])
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
            return None

        _persistent_containers[cache_key] = {
            "container_id": container_id,
            "port": port,
            "url": url,
        }

        logger.info("[MCPContainerMgr] ✅ %s ready at %s (container: %s)",
                    mcp_name, url, container_id[:12])
        return {"url": url, "transport": "streamable_http"}


def cleanup_persistent_containers():
    """Stop all persistent MCP containers (call on shutdown)."""
    for key, info in list(_persistent_containers.items()):
        cid = info.get("container_id", "")
        if cid:
            logger.info("[MCPContainerMgr] Stopping container %s", cid[:12])
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=10)
    _persistent_containers.clear()
