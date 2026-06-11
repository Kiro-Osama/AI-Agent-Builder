"""
Node 5: Sandbox Validator
===========================
Dispatches skill validation to Celery for isolated testing.
Waits for results and updates state.
Supports retry: sets sandbox_action='retry' if validation fails and retries remain.
"""
import logging
import time

from orchestrator.state import AgentBuilderState

logger = logging.getLogger(__name__)

MAX_SKILL_RETRIES = 3


async def sandbox_validator(state: AgentBuilderState) -> dict:
    """
    Node 5: Validate new skills in Docker sandbox.
    Dispatches Celery tasks and polls for results.

    Returns:
        validated_skills: Skills that passed validation
        sandbox_action: "proceed" or "retry"
        new_skills: Failed skills to retry (if sandbox_action == "retry")
    """
    new_skills = state.get("new_skills", [])

    if not new_skills:
        logger.info("🧪 Node 5: No new skills to validate, skipping")
        return {
            "validated_skills": state.get("retrieved_skills", []),
            "sandbox_action": "proceed",
        }

    logger.info(f"🧪 Node 5: Validating {len(new_skills)} skills in sandbox...")
    validated_skills = list(state.get("retrieved_skills", []))  # Start with existing
    failed_skills: list[dict] = []

    from worker.tasks.sandbox_validator import validate_skill

    for skill in new_skills:
        skill_id = skill["skill_id"]
        retry_count = skill.get("retry_count", 0)
        try:
            # Dispatch to Celery sandbox queue
            task = validate_skill.delay(skill_id=skill_id)

            # Poll for result (max 60s per skill)
            result = task.get(timeout=60)

            if result.get("success"):
                logger.info(f"  ✅ Skill passed: {skill_id}")
                skill["status"] = "active"
                skill["similarity"] = 1.0  # Newly created skills are exactly for this task
                validated_skills.append(skill)
            else:
                error = result.get("error", "Unknown error")
                logger.warning(f"  ❌ Skill failed: {skill_id} - {error}")
                if retry_count < MAX_SKILL_RETRIES:
                    skill["retry_count"] = retry_count + 1
                    skill["error_log"] = error
                    failed_skills.append(skill)
                else:
                    logger.warning(f"  ⛔ Max retries ({MAX_SKILL_RETRIES}) reached for {skill_id}")

        except Exception as e:
            logger.error(f"  Sandbox validation error for {skill_id}: {e}")
            if retry_count < MAX_SKILL_RETRIES:
                skill["retry_count"] = retry_count + 1
                skill["error_log"] = str(e)
                failed_skills.append(skill)

    logger.info(f"  Validated {len(validated_skills)} total skills, {len(failed_skills)} need retry")

    if failed_skills:
        return {
            "validated_skills": validated_skills,
            "new_skills": failed_skills,
            "missing_capabilities": [s.get("description", "") for s in failed_skills],
            "sandbox_action": "retry",
        }

    return {
        "validated_skills": validated_skills,
        "sandbox_action": "proceed",
    }
