"""
Node 4: Skill Creator Agent
=============================
Creates new skills dynamically when the Needs Assessment identifies gaps.
Generates code, prompts, and tool schemas, then INSERTs into DB as 'pending'.
"""
import json
import logging
import os
import uuid

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client
from core.embeddings import embedding_generator
from core.models import Skill

logger = logging.getLogger(__name__)

SYNC_DB_URL = os.getenv(
    "ALEMBIC_DATABASE_URL",
    "postgresql://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db",
)

SKILL_CREATOR_PROMPT = """You are an expert Python developer and AI Skill Builder.
Your job is to create a NEW skill that provides a missing capability.

Missing Capability: {missing_capability}
Context (User's original task): {user_query}

Instructions:
1. Create a skill with a clear system_prompt for the AI agent.
2. Define tool schemas (function definitions) that the agent can use.
3. Write Python code that implements these tools.
4. The code must be self-contained and testable.
5. Include a --test flag that runs basic validation.

Output ONLY valid JSON:
{{
    "skill_id": "descriptive-skill-name-v1",
    "skill_name": "Human Readable Name",
    "description": "What this skill does",
    "system_prompt": "You are an expert at...",
    "tools_schema": [
        {{
            "name": "function_name",
            "description": "What this function does",
            "parameters": {{
                "type": "object",
                "properties": {{}},
                "required": []
            }}
        }}
    ],
    "code": "import sys\\n\\ndef main():\\n    if '--test' in sys.argv:\\n        print('TEST PASSED')\\n        return\\n    # Main implementation\\n\\nif __name__ == '__main__':\\n    main()",
    "execution_env": "python:3.11-slim",
    "env_requirements": [],
    "assets": []
}}"""


async def skill_creator(state: AgentBuilderState) -> dict:
    """
    Node 4: Create new skills for missing capabilities.
    Inserts into DB with status='pending'.
    """
    missing_capabilities = state.get("missing_capabilities", [])
    user_query = state["user_query"]

    if not missing_capabilities:
        logger.info("⚒️ Node 4: No missing capabilities, skipping")
        return {"new_skills": []}

    logger.info(f"⚒️ Node 4: Creating {len(missing_capabilities)} new skills...")
    new_skills = []

    for capability in missing_capabilities:
        try:
            result = await openrouter_client.chat_completion_json(
                messages=[
                    {
                        "role": "system",
                        "content": SKILL_CREATOR_PROMPT.format(
                            missing_capability=capability,
                            user_query=user_query,
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Create a skill for: {capability}",
                    },
                ],
                temperature=0.4,
            )

            skill_id = result.get("skill_id", f"auto-skill-{uuid.uuid4().hex[:8]}")

            # Generate embedding for the skill description
            description = result.get("description", capability)
            try:
                embedding = await embedding_generator.generate(description)
            except Exception:
                embedding = None

            # Build skill_data payload
            skill_data = {
                "system_prompt": result.get("system_prompt", ""),
                "tools_schema": result.get("tools_schema", []),
                "code": result.get("code", ""),
                "execution_env": result.get("execution_env", "python:3.11-slim"),
                "env_requirements": result.get("env_requirements", []),
                "assets": result.get("assets", []),
            }

            # Insert into database
            engine = create_engine(SYNC_DB_URL)
            session = Session(engine)
            try:
                session.execute(
                    insert(Skill).values(
                        skill_id=skill_id,
                        skill_name=result.get("skill_name", skill_id),
                        description=description,
                        embedding=str(embedding) if embedding else None,
                        status="pending",
                        version="v1.0",
                        skill_data=skill_data,
                    )
                )
                session.commit()
                logger.info(f"  Created skill: {skill_id}")
            except Exception as e:
                session.rollback()
                logger.error(f"  DB insert failed for skill {skill_id}: {e}")
                raise
            finally:
                session.close()

            new_skills.append({
                "skill_id": skill_id,
                "skill_name": result.get("skill_name", skill_id),
                "description": description,
                "skill_data": skill_data,
                "status": "pending",
            })

        except Exception as e:
            logger.error(f"  Skill creation failed for '{capability}': {e}")
            state.get("errors", []).append(f"Skill creation for '{capability}': {str(e)}")

    logger.info(f"  Created {len(new_skills)} new skills")
    return {"new_skills": new_skills}
