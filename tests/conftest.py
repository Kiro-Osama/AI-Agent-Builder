"""
Shared test fixtures for the Agent Builder test suite.
"""
import os

import pytest

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ALEMBIC_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture
def sample_build_request():
    return {
        "query": "Build a GitHub PR monitor that sends Slack notifications",
        "preferred_model": None,
        "max_mcps": 5,
        "enable_skill_creation": True,
    }


@pytest.fixture
def sample_mcp_config():
    return {
        "mcp_name": "filesystem",
        "docker_image": "ghcr.io/mark3labs/mcp-filesystem-server:latest",
        "run_config": {
            "volumes": {"/host/workspace": "/workspace"},
            "command": ["/workspace"],
        },
        "tools_provided": [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ],
    }


@pytest.fixture
def sample_skill():
    return {
        "skill_id": "test-skill",
        "skill_name": "Test Skill",
        "description": "A test skill for unit testing",
        "system_prompt": "You are a test assistant.",
        "status": "active",
        "similarity": 0.8,
    }
