"""
Core ORM Models
================
SQLAlchemy models for MCPs, Skills, and Build History tables.
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from core.db import Base


class MCP(Base):
    """
    MCP (Model Context Protocol) tools.
    STATIC - pulled from Docker Hub, never created dynamically.
    The system only SELECTS from this table.
    """

    __tablename__ = "mcps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mcp_name = Column(String(100), unique=True, nullable=False)
    docker_image = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    tools_provided = Column(JSONB, server_default=text("'[]'::jsonb"))
    default_ports = Column(JSONB, server_default=text("'[]'::jsonb"))
    category = Column(String(50))
    run_config = Column(JSONB, server_default=text("'{}'::jsonb"))
    requires_user_config = Column(Boolean, default=False, server_default=text("false"))
    config_schema = Column(JSONB, server_default=text("'[]'::jsonb"))
    shared_container_id = Column(String(100))
    shared_container_status = Column(String(20))
    embedding = Column(Vector(768))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mcp_name": self.mcp_name,
            "docker_image": self.docker_image,
            "description": self.description,
            "tools_provided": self.tools_provided,
            "default_ports": self.default_ports,
            "category": self.category,
            "run_config": self.run_config,
            "requires_user_config": self.requires_user_config or False,
            "config_schema": self.config_schema or [],
            "is_active": self.is_active,
            "has_embedding": self.embedding is not None,
        }


class Skill(Base):
    """
    Dynamic skills that the Builder Agent can create from scratch.
    Contains code, system prompts, and tool schemas.
    """

    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id = Column(String(255), unique=True, nullable=False)
    skill_name = Column(String(200))
    description = Column(Text)
    embedding = Column(Vector(768))
    status = Column(String(50), default="pending")  # pending | testing | active | failed
    version = Column(String(20), default="v1.0")
    source_folder_path = Column(String(255))
    skill_data = Column(JSONB, server_default=text("'{}'::jsonb"))
    category = Column(String(50))
    source = Column(String(50))  # "seeded" | "pipeline"
    system_prompt = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    error_log = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "description": self.description,
            "status": self.status,
            "version": self.version,
            "category": self.category,
            "source": self.source,
            "source_folder_path": self.source_folder_path,
            "has_embedding": self.embedding is not None,
            "skill_data": self.skill_data,
        }


class BuildHistory(Base):
    """Track all build requests and their pipeline progress."""

    __tablename__ = "build_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(String(255), unique=True, nullable=False)
    user_query = Column(Text, nullable=False)
    status = Column(String(50), default="queued")  # queued | processing | completed | failed
    current_node = Column(String(50))
    result_template = Column(JSONB)
    selected_mcps = Column(JSONB, server_default=text("'[]'::jsonb"))
    selected_skills = Column(JSONB, server_default=text("'[]'::jsonb"))
    processing_log = Column(JSONB, server_default=text("'[]'::jsonb"))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "task_id": self.task_id,
            "user_query": self.user_query,
            "status": self.status,
            "current_node": self.current_node,
            "result_template": self.result_template,
            "selected_mcps": self.selected_mcps,
            "selected_skills": self.selected_skills,
            "processing_log": self.processing_log,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class Workflow(Base):
    """Multi-agent workflow definition built by the Workflow Planner."""

    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(200))
    description = Column(Text)
    user_query = Column(Text, nullable=False)
    topology = Column(String(50), nullable=False, default="sequential")
    workflow_config = Column(JSONB, server_default=text("'{}'::jsonb"))
    agents = Column(JSONB, server_default=text("'[]'::jsonb"))
    shared_state_schema = Column(JSONB, server_default=text("'{}'::jsonb"))
    status = Column(String(50), default="planning")
    build_task_ids = Column(JSONB, server_default=text("'[]'::jsonb"))
    error_log = Column(Text)
    sub_build_max_mcps = Column(Integer, nullable=True)
    sub_build_max_skills = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "user_query": self.user_query,
            "topology": self.topology,
            "workflow_config": self.workflow_config,
            "agents": self.agents,
            "shared_state_schema": self.shared_state_schema,
            "status": self.status,
            "build_task_ids": self.build_task_ids,
            "error_log": self.error_log,
            "sub_build_max_mcps": self.sub_build_max_mcps,
            "sub_build_max_skills": self.sub_build_max_skills,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkflowExecution(Base):
    """Runtime state for a workflow chat session."""

    __tablename__ = "workflow_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(String(255), nullable=False)
    conversation_id = Column(String(255), nullable=False)
    shared_state = Column(JSONB, server_default=text("'{}'::jsonb"))
    execution_log = Column(JSONB, server_default=text("'[]'::jsonb"))
    current_agent = Column(String(100))
    status = Column(String(50), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "workflow_id": self.workflow_id,
            "conversation_id": self.conversation_id,
            "shared_state": self.shared_state,
            "execution_log": self.execution_log,
            "current_agent": self.current_agent,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
