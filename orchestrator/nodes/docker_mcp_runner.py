"""
Node 7: Docker MCP Runner
============================
Validates selected MCPs and prepares them for chat-time execution.
Containers are NO LONGER started during build — they start on-demand when
the user opens the chat. This node just pulls images and passes metadata through.
"""
import logging

from orchestrator.state import AgentBuilderState

logger = logging.getLogger(__name__)


async def docker_mcp_runner(state: AgentBuilderState) -> dict:
    """
    Node 7: Validate and prepare MCP configs for chat-time container launch.
    
    Previously tried to start containers here, which was unreliable.
    Now we just validate configs and pre-pull images if possible.
    Actual container launch happens in core/agent_session.py during chat.
    """
    selected_tools = state.get("selected_tools", {})
    selected_mcps = selected_tools.get("mcps", [])

    if not selected_mcps:
        logger.info("🐳 Node 7: No MCPs to prepare")
        return {"running_mcps": []}

    logger.info(f"🐳 Node 7: Preparing {len(selected_mcps)} MCP(s) for chat-time launch...")
    running_mcps = []

    for mcp in selected_mcps:
        mcp_name = mcp.get("mcp_name", "unknown")
        docker_image = mcp.get("docker_image", "")
        run_config = mcp.get("run_config", {}) or {}

        if not docker_image:
            logger.warning(f"  ⚠️ {mcp_name}: no docker_image, skipping")
            continue

        # Try to pre-pull the image (best effort, don't fail the pipeline)
        try:
            import docker as docker_lib
            client = docker_lib.from_env()
            logger.info(f"  📥 Pulling {docker_image}...")
            client.images.pull(docker_image)
            logger.info(f"  ✅ {mcp_name}: image ready")
        except Exception as e:
            logger.warning(f"  ⚠️ {mcp_name}: pre-pull failed ({e}), will pull at chat time")

        # Pass through all metadata for template_builder
        running_mcps.append({
            "mcp_name": mcp_name,
            "docker_image": docker_image,
            "run_config": run_config,
            "tools_provided": mcp.get("tools_provided", []),
            "default_ports": mcp.get("default_ports", []),
            "category": mcp.get("category", ""),
            "status": "ready",  # Ready for chat-time launch
            "transport": run_config.get("transport", "stdio"),
        })

    logger.info(f"  {len(running_mcps)}/{len(selected_mcps)} MCPs prepared")
    return {"running_mcps": running_mcps}
