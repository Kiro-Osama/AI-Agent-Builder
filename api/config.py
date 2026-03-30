"""
FastAPI Application - Config
=============================
Settings loaded from environment variables.
"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from env vars."""

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db"
    alembic_database_url: str = "postgresql://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # OpenRouter (chat only - embeddings are FREE local)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_chat_model: str = "nvidia/nemotron-3-super-120b-a12b:free"

    # Skills
    skills_dir: str = "/app/skills"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
