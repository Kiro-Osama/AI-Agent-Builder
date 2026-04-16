"""Request schemas for the Agent Builder API."""
from typing import Literal

from pydantic import BaseModel, Field

LlmProvider = Literal["openrouter", "ollama", "ollama_remote"]


class BuildRequest(BaseModel):
    """Request to build an agent from a user query."""
    query: str = Field(..., min_length=5, max_length=5000, description="User's task description")
    preferred_model: str | None = Field(None, description="Preferred OpenRouter model ID")
    llm_provider: LlmProvider | None = Field(
        None,
        description="LLM backend: openrouter, ollama (local), or ollama_remote (OLLAMA_REMOTE_BASE_URL).",
    )
    max_mcps: int = Field(5, ge=1, le=10, description="Max number of MCPs to select")
    enable_skill_creation: bool = Field(True, description="Allow dynamic skill creation")
