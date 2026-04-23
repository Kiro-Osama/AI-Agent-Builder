"""
FastAPI Application - Config
=============================
Settings loaded from environment variables.
Do not commit secrets; use `.env` or your orchestrator's secret store.
"""
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings from env vars."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Database (set via .env — no baked-in passwords)
    database_url: str = ""
    alembic_database_url: str = ""

    # Redis
    redis_url: str = ""

    # OpenRouter (chat only — embeddings use Gemini in auto_embed)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_chat_model: str = "openrouter/free"

    # CORS: comma-separated origins, e.g. "http://localhost:3000,https://app.example.com"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Skills
    skills_dir: str = "/app/skills"

    # LangSmith (optional — LangGraph / LangChain tracing when API key is set)
    langsmith_api_key: str = ""
    langchain_project: str = "agent_builder"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    @field_validator("database_url", "alembic_database_url", "redis_url", mode="before")
    @classmethod
    def strip_empty_to_default(cls, v: str) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @model_validator(mode="after")
    def validate_production_db(self) -> "Settings":
        if self.app_env == "production":
            if not self.database_url:
                raise ValueError("DATABASE_URL must be set in production")
            if not self.alembic_database_url:
                raise ValueError("ALEMBIC_DATABASE_URL must be set in production")
            if not self.redis_url:
                raise ValueError("REDIS_URL must be set in production")
            if "change_me" in self.database_url or "change_me" in self.alembic_database_url:
                raise ValueError("Replace placeholder database credentials in production")
        return self


settings = Settings()
