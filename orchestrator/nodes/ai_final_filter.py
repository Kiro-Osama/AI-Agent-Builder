"""
Node 6: AI Final Filter
=========================
Intelligently filters the tool pool to the absolute minimum required tools.
"""
import json
import logging

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)

AI_FINAL_FILTER_PROMPT = """You are the Final Selection AI for an Agent Builder system. You have a pool of retrieved tools (MCPs and Skills).

Task: {user_query}

Available Tool Pool:
{available_tools}

Instructions:
1. Strictly filter this pool. Select ONLY the absolute minimum necessary tools required to execute the task.
2. Discard any tools that are not directly required.
3. For MCPs, consider their Docker images and tools they provide.
4. For Skills, consider their capabilities and system prompts.
5. Be very selective - more tools means more complexity and cost.

Output ONLY valid JSON:
{{
    "selected_mcps": [
        {{"id": 1, "mcp_name": "...", "reason": "why this MCP is needed"}}
    ],
    "selected_skills": [
        {{"skill_id": "...", "reason": "why this skill is needed"}}
    ],
    "reasoning": "Overall selection rationale"
}}"""


async def ai_final_filter(state: AgentBuilderState) -> dict:
    """
    Node 6: Final intelligent filtering of the tool pool.
    """
    user_query = state["user_query"]
    retrieved_mcps = state["retrieved_mcps"]
    validated_skills = state.get("validated_skills", [])

    logger.info(f"🎯 Node 6: Filtering {len(retrieved_mcps)} MCPs + {len(validated_skills)} Skills...")

    # Build the available tools pool
    tools_pool = {
        "mcps": [
            {
                "id": m["id"],
                "name": m["mcp_name"],
                "description": m["description"],
                "tools": m.get("tools_provided", []),
                "category": m.get("category"),
            }
            for m in retrieved_mcps
        ],
        "skills": [
            {
                "skill_id": s["skill_id"],
                "name": s.get("skill_name", s["skill_id"]),
                "description": s.get("description", ""),
            }
            for s in validated_skills
        ],
    }

    try:
        result = await openrouter_client.chat_completion_json(
            messages=[
                {
                    "role": "system",
                    "content": AI_FINAL_FILTER_PROMPT.format(
                        user_query=user_query,
                        available_tools=json.dumps(tools_pool, indent=2),
                    ),
                },
                {
                    "role": "user",
                    "content": f"Select the minimum tools needed for: {user_query}",
                },
            ],
            temperature=0.2,
        )

        # Map selected IDs back to full objects
        selected_mcp_ids = {m["id"] for m in result.get("selected_mcps", [])}
        selected_skill_ids = {s["skill_id"] for s in result.get("selected_skills", [])}

        selected_mcps = [m for m in retrieved_mcps if m["id"] in selected_mcp_ids]
        selected_skills = [s for s in validated_skills if s["skill_id"] in selected_skill_ids]

        # Fallback: if nothing was selected but we have tools, keep at least the best MCP
        if not selected_mcps and retrieved_mcps:
            selected_mcps = [retrieved_mcps[0]]
            logger.warning("  No MCPs selected by filter, keeping top match")

        logger.info(f"  Selected: {len(selected_mcps)} MCPs, {len(selected_skills)} Skills")
        return {
            "selected_tools": {
                "mcps": selected_mcps,
                "skills": selected_skills,
            }
        }

    except Exception as e:
        logger.error(f"AI Final Filter failed: {e}")
        # Fallback: keep top 3 MCPs and all validated skills
        return {
            "selected_tools": {
                "mcps": retrieved_mcps[:3],
                "skills": validated_skills,
            },
            "errors": state.get("errors", []) + [f"AI Final Filter: {str(e)}"],
        }
