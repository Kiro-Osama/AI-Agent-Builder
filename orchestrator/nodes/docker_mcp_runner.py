"""
Node 7: Docker MCP Runner
============================
Starts Docker containers for selected MCPs using their run_config.
Handles both stdio and http transport MCPs.
"""
import logging

from orchestrator.state import AgentBuilderState
from core.docker_manager import DockerManager

logger = logging.getLogger(__name__)


async def docker_mcp_runner(state: AgentBuilderState) -> dict:
    """
    Node 7: Start Docker containers for each selected MCP.
    Uses run_config from the DB to know HOW to launch each image.
    """
    selected_tools = state.get("selected_tools", {})
    selected_mcps = selected_tools.get("mcps", [])

    if not selected_mcps:
        logger.info("🐳 Node 7: No MCPs to launch")
        return {"running_mcps": []}

    logger.info(f"🐳 Node 7: Launching {len(selected_mcps)} MCP containers...")
    running_mcps = []

    try:
        docker_mgr = DockerManager()

        for mcp in selected_mcps:
            mcp_name = mcp["mcp_name"]
            docker_image = mcp["docker_image"]
            run_config = mcp.get("run_config", {}) or {}

            try:
                # Extract run config parameters
                transport = run_config.get("transport", "stdio")
                stdin_open = run_config.get("stdin_open", True)
                command = run_config.get("command", None)
                volumes = run_config.get("volumes", {})
                environment = run_config.get("environment", {})
                expose_ports = run_config.get("expose_ports", {})
                network_mode = run_config.get("network_mode", None)

                # Filter out "REQUIRED" placeholder env vars (user hasn't set them)
                real_env = {
                    k: v for k, v in environment.items()
                    if v and v != "REQUIRED"
                }

                # Build container name
                container_name = f"agentbuilder-{mcp_name}"

                logger.info(f"  🚀 Starting {mcp_name} (transport={transport})...")
                logger.info(f"     Image: {docker_image}")
                logger.info(f"     Config: cmd={command}, volumes={volumes}, stdin={stdin_open}")

                if transport == "stdio":
                    # stdio MCPs need -i flag and may need specific command args
                    result = docker_mgr.start_mcp_stdio(
                        image_name=docker_image,
                        container_name=container_name,
                        command=command if command else None,
                        volumes=volumes,
                        environment=real_env,
                        stdin_open=stdin_open,
                    )
                else:
                    # HTTP MCPs need port mapping
                    result = docker_mgr.start_mcp(
                        image_name=docker_image,
                        container_name=container_name,
                        environment=real_env,
                    )

                # Get the primary port (for http transport)
                ports = result.get("ports", {})
                primary_port = list(ports.values())[0] if ports else None

                running_mcps.append({
                    "mcp_name": mcp_name,
                    "docker_image": docker_image,
                    "container_id": result["container_id"],
                    "container_name": result["container_name"],
                    "running_port": primary_port,
                    "all_ports": ports,
                    "transport": transport,
                    "tools_provided": mcp.get("tools_provided", []),
                    "status": result["status"],
                    "run_config": run_config,
                })

                logger.info(f"  ✅ {mcp_name} started (port={primary_port}, transport={transport})")

            except Exception as e:
                logger.error(f"  ❌ Failed to start {mcp_name}: {e}")
                running_mcps.append({
                    "mcp_name": mcp_name,
                    "docker_image": docker_image,
                    "error": str(e),
                    "status": "failed",
                    "transport": run_config.get("transport", "stdio"),
                })

    except Exception as e:
        logger.error(f"Docker manager initialization failed: {e}")
        return {
            "running_mcps": [],
            "errors": state.get("errors", []) + [f"Docker MCP Runner: {str(e)}"],
        }

    running_count = len([m for m in running_mcps if m.get("status") != "failed"])
    logger.info(f"  {running_count}/{len(selected_mcps)} MCPs running")
    return {"running_mcps": running_mcps}
