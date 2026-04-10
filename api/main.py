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
from api.routers import build, status, templates, chat, embeddings, skills_seed, admin, manual_build

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
    logger.info("🚀 Agent Builder V5 API starting...")
    logger.info(f"   Environment: {settings.app_env}")
    logger.info(f"   Model: {settings.default_chat_model}")

    async def ttl_cleanup_loop() -> None:
        while True:
            try:
                await asyncio.sleep(60)
                from core.agent_session import cleanup_expired_sessions

                removed = await cleanup_expired_sessions()
                for key in removed:
                    chat.conversations.pop(key, None)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Session TTL cleanup failed: %s", e)

    ttl_task = asyncio.create_task(ttl_cleanup_loop())

    yield

    ttl_task.cancel()
    try:
        await ttl_task
    except asyncio.CancelledError:
        pass

    logger.info("🛑 Cleaning up MCP sessions...")
    from core.agent_session import cleanup_all_sessions

    await cleanup_all_sessions()

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
