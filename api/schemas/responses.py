"""Response schemas for the Agent Builder API."""
from datetime import datetime

from pydantic import BaseModel, Field


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
    progress: float = 0.0
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
