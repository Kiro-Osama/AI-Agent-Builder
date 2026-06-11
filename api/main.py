"""
FastAPI Application - Main Entry Point
========================================
The API Gateway for the Agent Builder System V5.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from core.langsmith_env import apply_langsmith_env

apply_langsmith_env(
    langsmith_api_key=settings.langsmith_api_key or None,
    langchain_project=settings.langchain_project or None,
    langchain_endpoint=settings.langchain_endpoint or None,
)

from api.routers import build, status, templates, chat, embeddings, skills_seed, admin, manual_build, workflow, dashboard, import_export

# -----------------------------------------------
# Logging setup
# -----------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# -----------------------------------------------
# App Lifespan
# -----------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("🚀 Agent Builder V5 API starting (DeepAgent Runtime)...")
    logger.info(f"   Environment: {settings.app_env}")
    logger.info(f"   Model: {settings.default_chat_model}")

    # Periodic cleanup of stale conversation histories
    async def ttl_cleanup_loop() -> None:
        import os as _os
        ttl_seconds = int(_os.getenv("SESSION_TTL_MINUTES", "60")) * 60
        max_sessions = 500  # hard cap to prevent OOM
        while True:
            try:
                await asyncio.sleep(60)
                import time
                now = time.time()

                # Clean up chat sessions
                from api.routers.chat import conversations, agent_configs, _session_timestamps

                # Evict sessions older than TTL
                stale_keys = [
                    k for k, ts in _session_timestamps.items()
                    if now - ts > ttl_seconds
                ]
                for k in stale_keys:
                    conversations.pop(k, None)
                    _session_timestamps.pop(k, None)
                if stale_keys:
                    logger.info("Cleanup: evicted %d stale chat session(s)", len(stale_keys))

                # Evict excess sessions if over hard cap (oldest first)
                if len(conversations) > max_sessions:
                    sorted_keys = sorted(_session_timestamps.items(), key=lambda x: x[1])
                    to_remove = len(conversations) - max_sessions
                    for k, _ in sorted_keys[:to_remove]:
                        conversations.pop(k, None)
                        _session_timestamps.pop(k, None)
                    logger.warning("Cleanup: evicted %d excess sessions (cap=%d)", to_remove, max_sessions)

                # Evict agent configs that have no active sessions
                active_task_ids = {k.split(":")[0] for k in conversations}
                stale_configs = [tid for tid in agent_configs if tid not in active_task_ids]
                for tid in stale_configs:
                    agent_configs.pop(tid, None)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Cleanup loop error: %s", e)

    ttl_task = asyncio.create_task(ttl_cleanup_loop())

    yield

    ttl_task.cancel()
    try:
        await ttl_task
    except asyncio.CancelledError:
        pass

    logger.info("🛑 Cleaning up...")

    from core.workflow_session import cleanup_all_workflow_sessions
    await cleanup_all_workflow_sessions()

    from core.shared_mcp_pool import shared_pool
    await shared_pool.shutdown()

    logger.info("🛑 Agent Builder V5 API shut down.")


# -----------------------------------------------
# FastAPI App
# -----------------------------------------------
app = FastAPI(
    title="Agent Builder System V5",
    description="Dynamic AI Agent Builder with LangGraph Orchestration, MCP Tools, and Skill Creation",
    version="5.0.0",
    lifespan=lifespan,
)

# -----------------------------------------------
# CORS Middleware
# -----------------------------------------------
_cors_list = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------
# Include Routers
# -----------------------------------------------
app.include_router(build.router, prefix="/api/v1", tags=["Build"])
app.include_router(status.router, prefix="/api/v1", tags=["Status"])
app.include_router(templates.router, prefix="/api/v1", tags=["Templates"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(embeddings.router, prefix="/api/v1", tags=["Embeddings"])
app.include_router(skills_seed.router, prefix="/api/v1", tags=["Skills Seed"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])
app.include_router(manual_build.router, prefix="/api/v1", tags=["Manual Build"])
app.include_router(workflow.router, prefix="/api/v1", tags=["Workflows"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["Dashboard"])
app.include_router(import_export.router, prefix="/api/v1", tags=["Import / Export"])


# -----------------------------------------------
# Health Check
# -----------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "5.0.0",
        "environment": settings.app_env,
    }
