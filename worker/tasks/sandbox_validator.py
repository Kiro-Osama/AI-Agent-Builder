"""
Sandbox Validator Task
=======================
Celery sub-task: Tests a skill in an isolated Docker container.
Updates skill status to 'active' or 'failed'.
"""
import logging
import os
from datetime import datetime, timezone

from worker.celery_app import app
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from core.models import Skill

logger = logging.getLogger(__name__)

_SYNC_DB_URL = os.getenv("ALEMBIC_DATABASE_URL", "").strip()
if not _SYNC_DB_URL:
    raise RuntimeError(
        "ALEMBIC_DATABASE_URL is required for sandbox_validator (sync PostgreSQL URL)."
    )


def get_sync_session() -> Session:
    engine = create_engine(_SYNC_DB_URL)
    return Session(engine)


@app.task(bind=True, name="worker.tasks.sandbox_validator.validate_skill")
def validate_skill(self, skill_id: str) -> dict:
    """
    Test a skill in an isolated Docker container.

    1. Reads skill code from skills table
    2. Spins up a sandbox container
    3. Runs the skill code
    4. Validates the output
    5. Updates skill status (active/failed)

    Args:
        skill_id: The skill_id to validate

    Returns:
        Validation result dict
    """
    logger.info(f"🧪 Validating skill: {skill_id}")
    session = get_sync_session()

    try:
        # Fetch skill from DB
        skill = session.query(Skill).filter_by(skill_id=skill_id).first()
        if not skill:
            return {"success": False, "error": f"Skill {skill_id} not found"}

        # Update status to testing
        skill.status = "testing"
        session.commit()

        # Get skill data
        skill_data = skill.skill_data or {}
        execution_env = skill_data.get("execution_env", "python:3.11-slim")
        code = skill_data.get("code", "")
        tools_schema = skill_data.get("tools_schema", [])

        if not code:
            # If no code, just validate the schema
            if tools_schema and skill_data.get("system_prompt"):
                skill.status = "active"
                session.commit()
                return {"success": True, "message": "Schema-only skill validated"}
            else:
                skill.status = "failed"
                skill.error_log = "No code or valid schema found"
                session.commit()
                return {"success": False, "error": "No code or schema"}

        # Run in sandbox
        from core.docker_manager import docker_manager

        # Write code to temp file in skills dir
        skills_dir = os.getenv("SKILLS_DIR", "/app/skills")
        skill_dir = os.path.join(skills_dir, skill_id)
        os.makedirs(skill_dir, exist_ok=True)

        code_path = os.path.join(skill_dir, "main.py")
        with open(code_path, "w") as f:
            f.write(code)

        # Test execution in sandbox
        result = docker_manager.run_sandbox(
            image=execution_env,
            command=f"python /skill/main.py --test",
            timeout=30,
            volumes={skill_dir: {"bind": "/skill", "mode": "ro"}},
        )

        if result["success"]:
            skill.status = "active"
            skill.source_folder_path = skill_dir
            skill.error_log = None
            logger.info(f"✅ Skill validated: {skill_id}")
        else:
            skill.retry_count += 1
            if skill.retry_count >= skill.max_retries:
                skill.status = "failed"
                skill.error_log = result.get("stderr", "Unknown error")
                logger.error(f"❌ Skill failed permanently: {skill_id}")
            else:
                skill.status = "pending"  # Will be retried
                skill.error_log = result.get("stderr", "")
                logger.warning(f"⚠️ Skill validation failed, retry {skill.retry_count}/{skill.max_retries}: {skill_id}")

        session.commit()

        return {
            "success": result["success"],
            "skill_id": skill_id,
            "status": skill.status,
            "exit_code": result.get("exit_code"),
            "stdout": result.get("stdout", "")[:500],
            "stderr": result.get("stderr", "")[:500],
        }

    except Exception as e:
        logger.error(f"Sandbox validation error: {e}")
        try:
            skill = session.query(Skill).filter_by(skill_id=skill_id).first()
            if skill:
                skill.status = "failed"
                skill.error_log = str(e)
                session.commit()
        except Exception:
            session.rollback()

        return {"success": False, "error": str(e)}

    finally:
        session.close()
