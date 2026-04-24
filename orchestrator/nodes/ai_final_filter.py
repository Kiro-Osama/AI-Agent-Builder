"""
Node 6: AI Final Filter
=========================
Intelligently filters the tool pool to the minimum required tools.

Key design decisions:
- MCPs  = Docker containers; genuinely expensive — be selective.
- Skills = Knowledge overlays / system-prompt injections; zero runtime cost.
  A skill should be KEPT whenever it is relevant to the task.
"""
import json
import logging

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)

AI_FINAL_FILTER_PROMPT = """You are the Final Selection AI for an Agent Builder system.

Task: {user_query}

════ AVAILABLE TOOLS ════
{available_tools}
═════════════════════════

## Selection rules

### MCPs  (Docker containers — pick carefully)
- Each MCP starts a separate Docker container, so only include ones DIRECTLY needed.
- Evaluate by the tools they expose and whether those tools are required for the task.
- Prefer 1-3 MCPs maximum unless the task genuinely requires more.

### Skills  (Knowledge overlays — keep any that are relevant)
- Skills are NOT Docker containers; they add ZERO runtime overhead.
- A skill injects expert instructions into the agent's system prompt.
- KEEP a skill if it overlaps with ANY part of the task — even partially.
- Only DISCARD a skill if it is completely unrelated to the task topic.
- When in doubt, KEEP the skill; including an extra skill costs nothing.

## Similarity scores
Each tool has a `similarity` score (0–1) showing how well it matches the task query.
- similarity ≥ 0.55 → strongly relevant, include unless clearly wrong domain
- similarity 0.35–0.55 → likely useful, include for skills, evaluate for MCPs
- similarity < 0.35 → marginal; skip unless obviously needed

Output ONLY valid JSON — no markdown, no extra text:
{{
    "selected_mcps": [
        {{"id": "<exact id from pool>", "mcp_name": "...", "reason": "..."}}
    ],
    "selected_skills": [
        {{"skill_id": "<exact skill_id from pool>", "reason": "..."}}
    ],
    "reasoning": "Overall rationale"
}}"""


async def ai_final_filter(state: AgentBuilderState) -> dict:
    """
    Node 6: Final intelligent filtering of the tool pool.
    """
    user_query = state["user_query"]
    retrieved_mcps = state["retrieved_mcps"]
    # validated_skills is set by sandbox_validator (create_skill path).
    # On the "proceed" path, it's never set — fall back to retrieved_skills.
    validated_skills = state.get("validated_skills") or state.get("retrieved_skills", [])

    logger.info("🎯 Node 6: Filtering %d MCPs + %d Skills...", len(retrieved_mcps), len(validated_skills))

    # Build the available tools pool (include similarity score so LLM can use it)
    tools_pool = {
        "mcps": [
            {
                "id": str(m["id"]),          # always string to match LLM output
                "name": m["mcp_name"],
                "description": m["description"],
                "tools": m.get("tools_provided", []),
                "category": m.get("category", ""),
                "similarity": round(m.get("similarity", 0.0), 3),
            }
            for m in retrieved_mcps
        ],
        "skills": [
            {
                "skill_id": s["skill_id"],
                "name": s.get("skill_name", s["skill_id"]),
                "description": s.get("description", ""),
                "category": s.get("category", ""),
                "similarity": round(s.get("similarity", 0.0), 3),
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
                        available_tools=json.dumps(tools_pool, indent=1),
                    ),
                },
                {
                    "role": "user",
                    "content": f"Select the tools for: {user_query}",
                },
            ],
            temperature=0.2,
            max_tokens=1024,
        )

        # --- MCP mapping: compare as strings to avoid int vs str mismatch ---
        mcp_lookup = {str(m["id"]): m for m in retrieved_mcps}
        selected_mcp_ids = {str(m.get("id", "")) for m in result.get("selected_mcps", [])}
        selected_mcps = [mcp_lookup[sid] for sid in selected_mcp_ids if sid in mcp_lookup]

        # --- Skill mapping: normalise to lowercase-stripped ---
        skill_lookup = {s["skill_id"].strip().lower(): s for s in validated_skills}
        selected_skill_ids = {
            s.get("skill_id", "").strip().lower()
            for s in result.get("selected_skills", [])
        }
        selected_skills = [skill_lookup[sid] for sid in selected_skill_ids if sid in skill_lookup]

        logger.info(f"  Selected: {len(selected_mcps)} MCPs, {len(selected_skills)} Skills")
        return {
            "selected_tools": {
                "mcps": selected_mcps,
                "skills": selected_skills,
            }
        }

    except Exception as e:
        logger.error(f"AI Final Filter failed: {e}")
        return {
            "selected_tools": {
                "mcps": retrieved_mcps[:3],
                "skills": validated_skills,
            },
            "errors": state.get("errors", []) + [f"AI Final Filter: {str(e)}"],
        }
