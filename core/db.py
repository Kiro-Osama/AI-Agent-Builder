"""
Core Database Module
====================
Async SQLAlchemy engine + session factory for PostgreSQL + pgvector.
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# -----------------------------------------------
# Database URL from environment
# -----------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db",
)

# -----------------------------------------------
# Engine with connection pooling
# -----------------------------------------------
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("APP_ENV") == "development",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# -----------------------------------------------
# Session factory
# -----------------------------------------------
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# -----------------------------------------------
# Base class for ORM models
# -----------------------------------------------
class Base(DeclarativeBase):
    pass


# -----------------------------------------------
# Dependency for FastAPI
# -----------------------------------------------
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session with auto-rollback on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with get_session() as session:
        yield session
