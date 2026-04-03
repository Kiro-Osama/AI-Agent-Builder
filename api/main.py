"""
FastAPI Application - Main Entry Point
========================================
The API Gateway for the Agent Builder System V5.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.routers import build, status, templates, chat

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
    yield
    # Cleanup all MCP container sessions on shutdown
    logger.info("🛑 Cleaning up MCP sessions...")
    from core.agent_session import cleanup_all_sessions
    await cleanup_all_sessions()
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
