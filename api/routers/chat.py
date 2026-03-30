"""
Chat Router
=============
POST /api/v1/chat/{task_id} - Chat with a built agent.
GET  /api/v1/chat/{task_id}/history - Get conversation history.
"""
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory conversation store (keyed by conversation_id)
# In production, use Redis or DB
conversations: dict[str, list[dict]] = {}

# Store agent configs (loaded from build results)
agent_configs: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str | None = None  # Override model (e.g. switch to free model)


class ChatResponse(BaseModel):
    response: str
    agent_name: str
    model: str
    conversation_id: str


@router.post("/chat/{task_id}", response_model=ChatResponse)
async def chat_with_agent(task_id: str, request: ChatRequest):
    """
    Send a message to the agent built for this task.
    Uses the agent's system prompt and model from the build template.
    """
    from sqlalchemy import select, create_engine
    from sqlalchemy.orm import Session
    from core.models import BuildHistory

    SYNC_DB_URL = os.getenv(
        "ALEMBIC_DATABASE_URL",
        "postgresql://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db",
    )

    # Load agent config if not cached
    if task_id not in agent_configs:
        engine = create_engine(SYNC_DB_URL)
        session = Session(engine)
        try:
            build = session.query(BuildHistory).filter_by(task_id=task_id).first()
            if not build or not build.result_template:
                raise HTTPException(404, "Build not found or not completed")

            template = build.result_template
            agents = template.get("agents", [])
            if not agents:
                raise HTTPException(400, "No agents in template")

            # Use the first agent
            agent = agents[0]
            agent_configs[task_id] = {
                "agent_name": agent.get("agent_name", "AI_Assistant"),
                "system_prompt": agent.get("system_prompt", "You are a helpful AI assistant."),
                "model": agent.get(
                    "assigned_openrouter_model",
                    os.getenv("DEFAULT_CHAT_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"),
                ),
                "selected_mcps": agent.get("selected_mcps", []),
                "selected_skills": agent.get("selected_skills", []),
            }
        finally:
            session.close()
            engine.dispose()

    config = agent_configs[task_id]

    # Get or create conversation
    conv_id = request.conversation_id or str(uuid.uuid4())
    if conv_id not in conversations:
        conversations[conv_id] = []

    history = conversations[conv_id]

    # Add user message
    history.append({"role": "user", "content": request.message})

    # Build messages for the model
    messages = [
        {"role": "system", "content": config["system_prompt"]},
        *history,
    ]

    try:
        # Use user-specified model if provided, otherwise use agent's model
        if request.model:
            model = request.model
        else:
            model = config["model"]
            # Auto-fallback paid models to free in dev
            if "claude" in model or "gpt-4" in model:
                model = os.getenv("DEFAULT_CHAT_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

        response_text = await openrouter_client.chat_completion_text(
            messages=messages,
            model=model,
            temperature=0.7,
        )

        # Add assistant response to history
        history.append({"role": "assistant", "content": response_text})

        return ChatResponse(
            response=response_text,
            agent_name=config["agent_name"],
            model=model,
            conversation_id=conv_id,
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(500, f"Chat failed: {str(e)}")


@router.get("/chat/{task_id}/info")
async def get_agent_info(task_id: str):
    """Get agent info for a completed build."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from core.models import BuildHistory

    SYNC_DB_URL = os.getenv(
        "ALEMBIC_DATABASE_URL",
        "postgresql://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db",
    )

    engine = create_engine(SYNC_DB_URL)
    session = Session(engine)
    try:
        build = session.query(BuildHistory).filter_by(task_id=task_id).first()
        if not build or not build.result_template:
            raise HTTPException(404, "Build not found")

        template = build.result_template
        agents = template.get("agents", [])
        agent = agents[0] if agents else {}

        return {
            "task_id": task_id,
            "agent_name": agent.get("agent_name", "AI_Assistant"),
            "model": agent.get("assigned_openrouter_model", "unknown"),
            "system_prompt": agent.get("system_prompt", ""),
            "selected_mcps": agent.get("selected_mcps", []),
            "selected_skills": agent.get("selected_skills", []),
            "project_type": template.get("project_type", "single_agent"),
            "user_query": build.user_query,
        }
    finally:
        session.close()
        engine.dispose()
