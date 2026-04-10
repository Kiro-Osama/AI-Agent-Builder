"""
Node 4: Skill Creator Agent
=============================
Creates new skills dynamically when the Needs Assessment identifies gaps.
Generates code, prompts, and tool schemas, then INSERTs into DB as 'pending'.
"""
import json
import logging
import os
import re
import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client
from core.embeddings import embedding_generator
from core.models import Skill

logger = logging.getLogger(__name__)

_SYNC_DB_URL = os.getenv("ALEMBIC_DATABASE_URL", "").strip()
if not _SYNC_DB_URL:
    raise RuntimeError(
        "ALEMBIC_DATABASE_URL is required for skill_creator (sync PostgreSQL URL)."
    )

_engine = create_engine(_SYNC_DB_URL, pool_pre_ping=True, pool_size=3, max_overflow=3)

# --------------------------------------------------------------------------
# Compact methodology — safe for string operations (no braces from examples)
# --------------------------------------------------------------------------
_METHODOLOGY_BRIEF = """\
SKILL WRITING RULES (Anthropic methodology):
1. skill_id: short lowercase-kebab-case (e.g. "gitlab-pr-monitor").
2. description: PRIMARY trigger mechanism. Say WHAT it does AND WHEN to use it. Be slightly pushy so the agent doesn't under-trigger.
3. system_prompt: Write in imperative form. Explain the WHY behind constraints. Keep lean and general — don't over-fit to this single example.
4. tools_schema: include only tools that are deterministic/repetitive. Each tool description must say what it does AND when to call it.
5. code: self-contained Python, testable with --test flag, standard library + well-known packages only.
"""


def _load_methodology_brief() -> str:
    """
    Load only the brief rules section from the skill-creator DB skill (if seeded),
    avoiding code-example blocks that contain braces and break f-string templates.
    Falls back to _METHODOLOGY_BRIEF if DB is unavailable or empty.
    """
    try:
        with Session(_engine) as session:
            row = session.execute(
                select(Skill.system_prompt).where(Skill.skill_id == "skill-creator")
            ).scalar_one_or_none()

        if not row:
            return _METHODOLOGY_BRIEF

        # Extract lines from "### Skill Writing Guide" up to the first code block,
        # stripping any lines that contain raw braces (they break format strings).
        lines = row.splitlines()
        brief: list[str] = []
        in_section = False
        for line in lines:
            if "### Skill Writing Guide" in line or "### Writing Style" in line:
                in_section = True
            if in_section and line.strip().startswith("```"):
                break  # stop before any code block
            if in_section:
                # Skip lines containing unescaped braces
                if "{" not in line and "}" not in line:
                    brief.append(line)

        result = "\n".join(brief).strip()
        return result if len(result) > 100 else _METHODOLOGY_BRIEF

    except Exception as e:
        logger.warning("skill_creator: could not load methodology from DB: %s", e)
        return _METHODOLOGY_BRIEF


_METHODOLOGY = _load_methodology_brief()

# --------------------------------------------------------------------------
# JSON schema the LLM must fill — kept as a string constant (no .format needed)
# --------------------------------------------------------------------------
_JSON_SCHEMA = '''{
    "skill_id": "short-kebab-id",
    "skill_name": "Human Readable Name",
    "description": "What it does + when to trigger it.",
    "system_prompt": "Imperative instructions for the agent.",
    "tools_schema": [],
    "code": "import sys\\n\\ndef main():\\n    if '--test' in sys.argv:\\n        print('TEST PASSED')\\n        return\\n\\nif __name__ == '__main__':\\n    main()",
    "execution_env": "python:3.11-slim",
    "env_requirements": [],
    "assets": []
}'''

# System prompt is built once at module load — no runtime .format() on user data
_SYSTEM_MSG = (
    "You are an expert AI Skill Builder.\n\n"
    + _METHODOLOGY
    + "\n\nOutput ONLY a single valid JSON object matching this schema exactly "
    "(no markdown fences, no explanation, no extra keys):\n"
    + _JSON_SCHEMA
)


def _build_user_msg(missing_capability: str, user_query: str) -> str:
    return (
        f"Create a high-quality skill for this missing capability:\n"
        f"Capability: {missing_capability}\n"
        f"Task context: {user_query}"
    )


def _parse_skill_json(raw: str) -> dict:
    """
    Robust JSON extraction:
    1. Direct parse
    2. Strip markdown fences
    3. Regex extract first {...} block
    4. Fix single-quotes / trailing commas
    Raises ValueError if nothing works.
    """
    raw = raw.strip()

    # 1. Direct
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Strip fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Extract first JSON object
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # 4. Fix common model quirks
    fixed = cleaned.replace("'", '"')
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    m2 = re.search(r"\{[\s\S]*\}", fixed)
    if m2:
        try:
            return json.loads(m2.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse skill JSON. First 400 chars: {raw[:400]}")


async def skill_creator(state: AgentBuilderState) -> dict:
    """
    Node 4: Create new skills for missing capabilities.
    """
    missing_capabilities = state.get("missing_capabilities", [])
    user_query = state["user_query"]

    if not missing_capabilities:
        logger.info("⚒️ Node 4: No missing capabilities, skipping")
        return {"new_skills": []}

    logger.info(
        "⚒️ Node 4: Creating %d new skills...", len(missing_capabilities)
    )
    new_skills = []

    for capability in missing_capabilities:
        try:
            raw_response = await openrouter_client.chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_MSG},
                    {"role": "user", "content": _build_user_msg(capability, user_query)},
                ],
                temperature=0.3,
                max_tokens=3072,
            )
            raw_text = raw_response["choices"][0]["message"].get("content") or ""
            if not raw_text:
                logger.error("  Skill creator: model returned empty content for '%s'", capability)
                continue

            try:
                result = _parse_skill_json(raw_text)
            except ValueError as parse_err:
                logger.error("  Skill JSON parse failed for '%s': %s", capability, parse_err)
                continue

            skill_id = (result.get("skill_id") or f"auto-skill-{uuid.uuid4().hex[:8]}").strip()
            description = (result.get("description") or capability).strip()
            skill_name = (result.get("skill_name") or skill_id).strip()
            system_prompt_text = (result.get("system_prompt") or "").strip()

            # Generate embedding
            try:
                embedding = await embedding_generator.generate(description)
                vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            except Exception:
                vec_str = None

            skill_data = {
                "tools_schema": result.get("tools_schema") or [],
                "code": result.get("code") or "",
                "execution_env": result.get("execution_env") or "python:3.11-slim",
                "env_requirements": result.get("env_requirements") or [],
                "assets": result.get("assets") or [],
                "source": "pipeline",
            }

            # Upsert via raw SQL (avoids ORM mapped-column issues)
            with Session(_engine) as session:
                try:
                    session.execute(
                        text("""
                            INSERT INTO skills
                                (skill_id, skill_name, description, system_prompt,
                                 status, version, source, skill_data)
                            VALUES
                                (:skill_id, :skill_name, :description, :system_prompt,
                                 'pending', 'v1.0', 'pipeline', CAST(:skill_data AS jsonb))
                            ON CONFLICT (skill_id) DO UPDATE SET
                                skill_name    = EXCLUDED.skill_name,
                                description   = EXCLUDED.description,
                                system_prompt = EXCLUDED.system_prompt,
                                skill_data    = EXCLUDED.skill_data,
                                status        = 'pending',
                                source        = 'pipeline',
                                updated_at    = now()
                        """),
                        {
                            "skill_id": skill_id,
                            "skill_name": skill_name,
                            "description": description,
                            "system_prompt": system_prompt_text,
                            "skill_data": json.dumps(skill_data),
                        },
                    )
                    if vec_str:
                        session.execute(
                            text(
                                "UPDATE skills SET embedding = CAST(:vec AS vector) "
                                "WHERE skill_id = :sid"
                            ),
                            {"vec": vec_str, "sid": skill_id},
                        )
                    session.commit()
                    logger.info("  Created skill: %s", skill_id)
                except Exception as db_err:
                    session.rollback()
                    logger.error("  DB upsert failed for skill %s: %s", skill_id, db_err)
                    raise

            new_skills.append({
                "skill_id": skill_id,
                "skill_name": skill_name,
                "description": description,
                "skill_data": skill_data,
                "system_prompt": system_prompt_text,
                "status": "pending",
            })

        except Exception as e:
            logger.error("  Skill creation failed for '%s': %s", capability, e)
            state.get("errors", []).append(f"Skill creation for '{capability}': {str(e)}")

    logger.info("  Created %d new skills", len(new_skills))
    return {"new_skills": new_skills}
