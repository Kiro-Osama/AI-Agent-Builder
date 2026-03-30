"""
Node 5: Sandbox Validator
===========================
Dispatches skill validation to Celery for isolated testing.
Waits for results and updates state.
"""
import logging
import time

from orchestrator.state import AgentBuilderState

logger = logging.getLogger(__name__)


async def sandbox_validator(state: AgentBuilderState) -> dict:
    """
    Node 5: Validate new skills in Docker sandbox.
    Dispatches Celery tasks and polls for results.
    """
    new_skills = state.get("new_skills", [])

    if not new_skills:
        logger.info("🧪 Node 5: No new skills to validate, skipping")
        return {"validated_skills": state.get("retrieved_skills", [])}

    logger.info(f"🧪 Node 5: Validating {len(new_skills)} skills in sandbox...")
    validated_skills = list(state.get("retrieved_skills", []))  # Start with existing

    from worker.tasks.sandbox_validator import validate_skill

    for skill in new_skills:
        skill_id = skill["skill_id"]
        try:
            # Dispatch to Celery sandbox queue
            task = validate_skill.delay(skill_id=skill_id)

            # Poll for result (max 60s per skill)
            result = task.get(timeout=60)

            if result.get("success"):
                logger.info(f"  ✅ Skill passed: {skill_id}")
                skill["status"] = "active"
                validated_skills.append(skill)
            else:
                error = result.get("error", "Unknown error")
                logger.warning(f"  ❌ Skill failed: {skill_id} - {error}")
                # Don't add failed skills to validated list

        except Exception as e:
            logger.error(f"  Sandbox validation error for {skill_id}: {e}")

    logger.info(f"  Validated {len(validated_skills)} total skills")
    return {"validated_skills": validated_skills}
