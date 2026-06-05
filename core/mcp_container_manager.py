"""
MCP Container Manager — Dynamic Persistent Containers
========================================================
Starts MCP Docker containers ONCE in SSE mode on the compose network,
keeps them alive forever, and reuses them across all agent requests.

Architecture:
    1. Any stdio MCP requested → check if persistent container already running
    2. If not → docker run -d on compose network with INLINE Python wrapper
    3. The wrapper monkey-patches FastMCP to:
       - Bind 0.0.0.0 (accept connections from other containers)
       - Use SSE transport (simpler, more compatible than streamable-http)
       - Disable DNS rebinding protection (needed for Docker inter-container comms)
    4. agent-engine connects by container name (same Docker network)
    5. Container stays alive with --restart=unless-stopped
    6. Falls back to stdio if SSE mode fails

CRITICAL DESIGN NOTE:
    The agent-engine runs inside a Docker container but issues 'docker run'
    commands to the HOST Docker daemon (via mounted docker.sock). This means
    volume mount paths must be HOST paths, not container-internal paths.
    To avoid host-path translation issues (especially on Docker Desktop for
    Windows where paths go through /run/desktop/mnt/host/), we EMBED the
    wrapper script inline as a Python -c command. No volume mount needed.
"""
import asyncio
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

# In-memory registry: mcp_name -> container info
_running_containers: dict[str, dict] = {}
_lock = asyncio.Lock()

# Docker compose network name (auto-detected or fallback)
_COMPOSE_NETWORK: str | None = None

# Internal port — no need to publish, same Docker network
_INTERNAL_PORT = 8080

# Container name prefix
_CONTAINER_PREFIX = "mcp-persistent"


# ─── Inline wrapper script ───
# This gets passed as `python3 -c "..."` so no volume mount is needed.
# It monkey-patches FastMCP to run SSE on 0.0.0.0 with DNS rebinding disabled.
_INLINE_WRAPPER = r'''
import sys, os

script_path = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080

# Set sys.argv for the target script's argparser (use streamable-http
# since some scripts only accept that, but we'll override to SSE below)
sys.argv = [script_path, "--transport", "streamable-http", "--host", "0.0.0.0", "--port", str(port)]

import mcp.server.fastmcp.server as mcp_server
_orig_run = mcp_server.FastMCP.run

def _patched_run(self, transport="stdio", **kwargs):
    self.settings.host = "0.0.0.0"
    self.settings.port = port
    try:
        self.settings.transport_security.enable_dns_rebinding_protection = False
    except Exception:
        pass
    print(f"[MCP-Wrapper] SSE on 0.0.0.0:{port}", flush=True)
    _orig_run(self, transport="sse")

mcp_server.FastMCP.run = _patched_run

script_dir = os.path.dirname(os.path.abspath(script_path))
sys.path.insert(0, script_dir)
os.chdir(script_dir)

with open(script_path) as f:
    code = f.read()
exec(compile(code, script_path, "exec"), {"__name__": "__main__", "__file__": script_path})
'''


def _detect_compose_network() -> str:
    """Auto-detect the docker compose network name."""
    global _COMPOSE_NETWORK
    if _COMPOSE_NETWORK:
        return _COMPOSE_NETWORK

    try:
        result = subprocess.run(
            ["docker", "inspect", "agentbuilder-agent-engine",
             "--format", "{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            net_id = result.stdout.strip()
            result2 = subprocess.run(
                ["docker", "network", "inspect", net_id, "--format", "{{.Name}}"],
                capture_output=True, text=True, timeout=5,
            )
            if result2.returncode == 0 and result2.stdout.strip():
                _COMPOSE_NETWORK = result2.stdout.strip()
                logger.info("[MCPContainerMgr] Detected compose network: %s", _COMPOSE_NETWORK)
                return _COMPOSE_NETWORK
    except Exception as e:
        logger.warning("[MCPContainerMgr] Network detection failed: %s", e)

    _COMPOSE_NETWORK = "ai_agent_builder_antogravity_default"
    return _COMPOSE_NETWORK


def _container_name(mcp_name: str) -> str:
    return f"{_CONTAINER_PREFIX}-{mcp_name}"


def _is_container_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


def _remove_container(name: str):
    try:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
    except Exception:
        pass


# Well-known MCP images -> main script path
_KNOWN_SCRIPTS: dict[str, str] = {
    "ramgameer/pentest-mcp": "/opt/pentest-mcp/pentestMCP.py",
}


def _detect_main_script(docker_image: str) -> str | None:
    """
    Detect the main Python MCP script inside an image by inspecting
    its CMD and ENTRYPOINT.
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", docker_image,
             "--format", "{{.Config.Entrypoint}} {{.Config.Cmd}}"],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout.strip()

        # Look for .py files in the output
        import re
        py_files = re.findall(r'(/\S+\.py)', output)
        if py_files:
            return py_files[0]

    except Exception as e:
        logger.debug("[MCPContainerMgr] Script detection failed: %s", e)

    return None


def _get_main_script(docker_image: str) -> str | None:
    """Get the main Python script for an MCP image."""
    # Check well-known images first
    for image_pattern, script in _KNOWN_SCRIPTS.items():
        if image_pattern in docker_image:
            return script

    # Try auto-detection
    return _detect_main_script(docker_image)


def _wait_for_sse(container_name: str, timeout: int = 30) -> bool:
    """
    Wait until the MCP SSE endpoint responds inside the container.
    Uses 'docker exec' + curl to test from INSIDE the container,
    avoiding any Docker networking translation issues.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # Try to reach the SSE endpoint from inside the container
            result = subprocess.run(
                ["docker", "exec", container_name,
                 "python3", "-c",
                 f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{_INTERNAL_PORT}/sse', timeout=2)"],
                capture_output=True, text=True, timeout=5,
            )
            # Any HTTP response (even error) means the server is up
            if result.returncode == 0:
                return True
            # urllib raises on non-2xx, but the server IS responding
            if "HTTP Error" in result.stderr or "urlopen" in result.stderr:
                return True
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        time.sleep(1)
    return False


async def ensure_persistent_container(
    mcp_name: str,
    docker_image: str,
    run_config: dict,
    mcp_user_configs: dict | None = None,
) -> dict | None:
    """
    Ensure a persistent MCP container is running in SSE mode.

    Returns:
        {"url": "http://container-name:8080/sse", "transport": "sse"}
        or None if SSE mode not possible.
    """
    cname = _container_name(mcp_name)
    network = _detect_compose_network()
    sse_url = f"http://{cname}:{_INTERNAL_PORT}/sse"

    async with _lock:
        # ── Check in-memory registry ──
        if mcp_name in _running_containers:
            info = _running_containers[mcp_name]
            if _is_container_running(info["container_name"]):
                logger.info("[MCPContainerMgr] ✅ Reusing %s → %s", mcp_name, info["url"])
                return {"url": info["url"], "transport": "sse"}
            else:
                logger.warning("[MCPContainerMgr] %s died, restarting...", mcp_name)
                _remove_container(info["container_name"])
                _running_containers.pop(mcp_name, None)

        # ── Check for pre-existing container (from previous engine session) ──
        if _is_container_running(cname):
            logger.info("[MCPContainerMgr] ✅ Found pre-existing %s → %s", cname, sse_url)
            _running_containers[mcp_name] = {"container_name": cname, "url": sse_url}
            return {"url": sse_url, "transport": "sse"}

        # ── Find the main script ──
        main_script = _get_main_script(docker_image)
        if not main_script:
            logger.warning("[MCPContainerMgr] Cannot find main script for %s, skipping HTTP", docker_image)
            return None

        # ── Clean up any stopped container with same name ──
        _remove_container(cname)

        # ── Build docker run command ──
        # CRITICAL: We use `python3 -c "..."` with the wrapper embedded inline.
        # This avoids needing volume mounts for the wrapper, which would fail
        # because agent-engine sees /app/core/... (container path) but Docker
        # needs host paths for -v mounts.
        cmd = [
            "docker", "run", "-d",
            "--name", cname,
            "--network", network,
            "--restart", "unless-stopped",
            "--add-host", "host.docker.internal:host-gateway",
        ]

        # Volumes from run_config
        workspace = os.getenv("WORKSPACE_PATH", "/workspace")
        volumes = run_config.get("volumes", {})
        for host_path, container_path in volumes.items():
            actual = host_path.replace("/host/workspace", workspace)
            cmd.extend(["-v", f"{actual}:{container_path}"])

        # Environment
        env = dict(run_config.get("environment", {}))
        if mcp_user_configs and mcp_name in (mcp_user_configs or {}):
            env.update(mcp_user_configs[mcp_name])

        for key, val in env.items():
            if val and val != "REQUIRED" and key != "allowed_directory":
                actual_val = os.getenv(key, str(val))
                cmd.extend(["-e", f"{key}={actual_val}"])

        # Override entrypoint to python3 with inline wrapper
        cmd.extend(["--entrypoint", "python3"])

        # Image
        cmd.append(docker_image)

        # Args: -c "wrapper code" <main_script> <port>
        cmd.extend(["-c", _INLINE_WRAPPER, main_script, str(_INTERNAL_PORT)])

        logger.info("[MCPContainerMgr] Starting persistent container: %s (image=%s, script=%s)",
                     cname, docker_image, main_script)

        # ── Start container ──
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
            if result.returncode != 0:
                logger.error("[MCPContainerMgr] Failed to start %s: %s", mcp_name, result.stderr.strip())
                _remove_container(cname)
                return None
        except Exception as e:
            logger.error("[MCPContainerMgr] Error starting %s: %s", mcp_name, e)
            _remove_container(cname)
            return None

        # ── Wait for SSE endpoint ──
        logger.info("[MCPContainerMgr] Waiting for SSE endpoint on %s ...", cname)

        ready = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _wait_for_sse(cname, timeout=30)
        )

        if not ready:
            # Check logs for errors
            try:
                log_result = subprocess.run(
                    ["docker", "logs", "--tail", "15", cname],
                    capture_output=True, text=True, timeout=5,
                )
                logger.error("[MCPContainerMgr] %s logs:\n%s", mcp_name,
                            log_result.stdout + log_result.stderr)
            except Exception:
                pass

            if not _is_container_running(cname):
                logger.warning("[MCPContainerMgr] %s crashed", mcp_name)
            else:
                logger.warning("[MCPContainerMgr] %s running but SSE unreachable", mcp_name)
            _remove_container(cname)
            return None

        _running_containers[mcp_name] = {"container_name": cname, "url": sse_url}
        logger.info("[MCPContainerMgr] ✅ %s ready at %s (SSE, persistent)", mcp_name, sse_url)
        return {"url": sse_url, "transport": "sse"}


def list_persistent_containers() -> dict[str, dict]:
    """List all tracked persistent MCP containers."""
    result = {}
    for name, info in _running_containers.items():
        result[name] = {
            **info,
            "running": _is_container_running(info["container_name"]),
        }
    return result


def cleanup_all():
    """Stop and remove all persistent MCP containers."""
    for name, info in list(_running_containers.items()):
        logger.info("[MCPContainerMgr] Cleaning up %s", info["container_name"])
        _remove_container(info["container_name"])
    _running_containers.clear()
