"""
Node 3: Needs Assessment
=========================
Evaluates if retrieved tools cover all required capabilities.
Identifies missing skills that need to be created.
"""
import json
import logging
import re

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)


def _parse_assessment_json(raw: str) -> dict:
    """Robustly extract JSON from LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Cannot parse assessment JSON: {raw[:200]}")


NEEDS_ASSESSMENT_PROMPT = """You are the Orchestrator for an Agent Builder system.
Decide whether the retrieved tools/skills are sufficient, or whether a new skill must be created.

RULES:
1. MCPs (Docker containers) are STATIC — cannot be created.
2. Skills (prompt overlays) are DYNAMIC — CAN be created when missing.
3. A skill with similarity >= 0.40 covering the needed capability = MATCH. Do NOT recreate it.
4. Set action="create_skill" ONLY when a genuinely needed capability is COMPLETELY absent from ALL retrieved skills.

User Task: {user_query}

Retrieved MCPs:
{retrieved_mcps}

Retrieved Skills (sorted by relevance):
{retrieved_skills}

Output ONLY valid JSON:
{{"action":"proceed"|"create_skill","missing_capabilities":["only genuinely missing ones"],"reasoning":"brief"}}"""


async def needs_assessment(state: AgentBuilderState) -> dict:
    """
    Node 3: Check if tools cover the user's needs.
    Route to skill creation if gaps found.
    """
    user_query = state["user_query"]
    retrieved_mcps = state["retrieved_mcps"]
    retrieved_skills = state["retrieved_skills"]
    enable_skill_creation = state.get("enable_skill_creation", True)

    logger.info("📋 Node 3: Assessing needs (%d MCPs, %d Skills)...", len(retrieved_mcps), len(retrieved_skills))

    try:
        mcps_text = json.dumps([
            {"name": m["mcp_name"], "description": m["description"],
             "tools": [t.get("name", "") for t in (m.get("tools_provided") or [])],
             "similarity": round(m.get("similarity", 0), 3)}
            for m in retrieved_mcps
        ], indent=1)

        skills_text = json.dumps([
            {
                "skill_id": s["skill_id"],
                "description": s.get("description", "")[:200],
                "similarity": round(s.get("similarity", 0), 3),
            }
            for s in sorted(retrieved_skills, key=lambda x: x.get("similarity", 0), reverse=True)
        ], indent=1) if retrieved_skills else "[]"

        prompt_content = NEEDS_ASSESSMENT_PROMPT.format(
            user_query=user_query,
            retrieved_mcps=mcps_text,
            retrieved_skills=skills_text,
        )
        raw_result = await openrouter_client.chat_completion(
            messages=[
                {"role": "system", "content": prompt_content},
                {"role": "user", "content": f"Assess tools for: {user_query}"},
            ],
            temperature=0.2,
            max_tokens=512,
        )
        raw_text = raw_result["choices"][0]["message"].get("content") or ""
        result = _parse_assessment_json(raw_text)

        action = result.get("action", "proceed")
        missing = result.get("missing_capabilities", [])

        if not enable_skill_creation and action == "create_skill":
            action = "proceed"
            missing = []
            logger.info("  Skill creation disabled, proceeding with available tools")

        logger.info("  Assessment: action=%s, missing=%d capabilities", action, len(missing))
        return {
            "needs_action": action,
            "missing_capabilities": missing,
        }

    except Exception as e:
        logger.error("Needs assessment failed: %s", e)
        return {
            "needs_action": "proceed",
            "missing_capabilities": [],
            "errors": state.get("errors", []) + [f"Needs assessment: {str(e)}"],
        }
