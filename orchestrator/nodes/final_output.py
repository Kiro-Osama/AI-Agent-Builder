"""
Node 9: Final Output
======================
Validates and formats the final template for API delivery.
"""
import logging

from orchestrator.state import AgentBuilderState

logger = logging.getLogger(__name__)


async def final_output(state: AgentBuilderState) -> dict:
    """
    Node 9: Validate and finalize the template.
    """
    template = state.get("final_template", {})

    logger.info("📦 Node 9: Finalizing output...")

    # Validate template structure
    if not template.get("agents"):
        logger.warning("  Template has no agents, creating minimal output")
        template = {
            "project_type": "single_agent",
            "agents": [],
            "status": "failed",
            "errors": state.get("errors", ["No agents were configured"]),
        }

    # Add metadata
    template["pipeline_metadata"] = {
        "task_id": state.get("task_id"),
        "total_mcps_found": len(state.get("retrieved_mcps", [])),
        "total_skills_found": len(state.get("retrieved_skills", [])),
        "skills_created": len(state.get("new_skills", [])),
        "mcps_launched": len([
            m for m in state.get("running_mcps", [])
            if m.get("status") != "failed"
        ]),
        "errors": state.get("errors", []),
    }

    agent_name = template["agents"][0].get("agent_name", "?") if template.get("agents") else "none"
    logger.info(f"  ✅ Template finalized: agent={agent_name}")
    return {
        "final_template": template,
        "status": "completed",
    }
