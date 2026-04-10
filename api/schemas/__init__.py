"""
FastAPI API - Schemas
======================
Pydantic models for request/response validation.
"""
from datetime import datetime

from pydantic import BaseModel, Field


# -----------------------------------------------
# Request Schemas
# -----------------------------------------------

class BuildRequest(BaseModel):
    """Request to build an agent from a user query."""
    query: str = Field(..., min_length=5, max_length=5000, description="User's task description")
    preferred_model: str | None = Field(None, description="Preferred OpenRouter model ID")
    max_mcps: int = Field(5, ge=1, le=10, description="Max number of MCPs to select")
    enable_skill_creation: bool = Field(True, description="Allow dynamic skill creation")


# -----------------------------------------------
# Response Schemas
# -----------------------------------------------

class BuildResponse(BaseModel):
    """Response after submitting a build request."""
    task_id: str
    status: str = "queued"
    message: str = "Build request submitted successfully"


class StatusResponse(BaseModel):
    """Pipeline status response."""
    task_id: str
    status: str
    current_node: str | None = None
    progress: float = 0.0  # 0.0 to 1.0
    processing_log: list[dict] = Field(default_factory=list)
    result_template: dict | None = None
    error: str | None = None


class MCPInfo(BaseModel):
    """MCP tool information."""
    id: int
    mcp_name: str
    docker_image: str
    description: str
    tools_provided: list[dict] = Field(default_factory=list)
    category: str | None = None
    is_active: bool = True


class SkillInfo(BaseModel):
    """Skill information."""
    id: str
    skill_id: str
    skill_name: str | None = None
    description: str | None = None
    status: str = "pending"
    version: str = "v1.0"


class AgentTemplate(BaseModel):
    """The final agent configuration template."""
    project_type: str = "single_agent"
    agents: list[dict] = Field(default_factory=list)
    status: str = "ready_for_user_approval"


class TemplateListItem(BaseModel):
    """Summary item for template list endpoint."""
    id: str
    task_id: str
    user_query: str
    status: str
    created_at: datetime | None = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "5.0.0"
    services: dict[str, str] = Field(default_factory=dict)
