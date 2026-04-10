"""
API Schemas — Pydantic models for request/response validation.

Split into:
    requests    BuildRequest
    responses   BuildResponse, StatusResponse, AgentTemplate, etc.
"""
from api.schemas.requests import BuildRequest
from api.schemas.responses import (
    AgentTemplate,
    BuildResponse,
    HealthResponse,
    MCPInfo,
    SkillInfo,
    StatusResponse,
    TemplateListItem,
)

__all__ = [
    "BuildRequest",
    "BuildResponse",
    "StatusResponse",
    "MCPInfo",
    "SkillInfo",
    "AgentTemplate",
    "TemplateListItem",
    "HealthResponse",
]
