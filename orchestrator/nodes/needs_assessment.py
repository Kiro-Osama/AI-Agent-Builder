"""
Node 3: Needs Assessment
=========================
Evaluates if retrieved tools cover all required capabilities.
Identifies missing skills that need to be created.
"""
import json
import logging

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)

NEEDS_ASSESSMENT_PROMPT = """You are the Orchestrator for an Agent Builder system. Your job is to assess if the retrieved tools and skills cover ALL the capabilities needed for the user's task.

GOLDEN RULES:
1. MCPs (Docker tools) are STATIC and CANNOT be created. If a critical MCP is missing, report it.
2. Skills (Python scripts/prompts) are DYNAMIC and CAN be created if missing.

User Task: {user_query}

Retrieved MCPs (Docker tools):
{retrieved_mcps}

Retrieved Skills (Dynamic capabilities):
{retrieved_skills}

Instructions:
1. Check if the retrieved tools FULLY cover the user's task requirements.
2. If a critical Python-based capability is missing (like data analysis, text processing, etc.), add it to missing_capabilities.
3. If everything looks sufficient, output action "proceed".
4. MCPs cannot be created - if a critical hardware/system tool is missing, note it in the warnings.

Output ONLY valid JSON:
{{
    "action": "proceed" | "create_skill",
    "missing_capabilities": ["description of missing capability 1", ...],
    "warnings": ["any warnings about missing MCPs"],
    "reasoning": "brief explanation of your assessment"
}}"""


async def needs_assessment(state: AgentBuilderState) -> dict:
    """
    Node 3: Check if tools cover the user's needs.
    Route to skill creation if gaps found.
    """
    user_query = state["user_query"]
    retrieved_mcps = state["retrieved_mcps"]
    retrieved_skills = state["retrieved_skills"]
    enable_skill_creation = state.get("enable_skill_creation", True)

    logger.info(f"📋 Node 3: Assessing needs ({len(retrieved_mcps)} MCPs, {len(retrieved_skills)} Skills)...")

    try:
        # Format tools for prompt
        mcps_text = json.dumps([
            {"name": m["mcp_name"], "description": m["description"], "tools": m.get("tools_provided", []),
             "similarity": m.get("similarity", 0)}
            for m in retrieved_mcps
        ], indent=2)

        skills_text = json.dumps([
            {"name": s["skill_id"], "description": s.get("description", ""), "similarity": s.get("similarity", 0)}
            for s in retrieved_skills
        ], indent=2) if retrieved_skills else "[]"

        result = await openrouter_client.chat_completion_json(
            messages=[
                {
                    "role": "system",
                    "content": NEEDS_ASSESSMENT_PROMPT.format(
                        user_query=user_query,
                        retrieved_mcps=mcps_text,
                        retrieved_skills=skills_text,
                    ),
                },
                {
                    "role": "user",
                    "content": f"Assess the tools for this task: {user_query}",
                },
            ],
            temperature=0.2,
        )

        action = result.get("action", "proceed")
        missing = result.get("missing_capabilities", [])

        # If skill creation is disabled, always proceed
        if not enable_skill_creation and action == "create_skill":
            action = "proceed"
            missing = []
            logger.info("  Skill creation disabled, proceeding with available tools")

        logger.info(f"  Assessment: action={action}, missing={len(missing)} capabilities")
        return {
            "needs_action": action,
            "missing_capabilities": missing,
        }

    except Exception as e:
        logger.error(f"Needs assessment failed: {e}")
        return {
            "needs_action": "proceed",
            "missing_capabilities": [],
            "errors": state.get("errors", []) + [f"Needs assessment: {str(e)}"],
        }
