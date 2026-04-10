"""Tests for core.agent_session — session management and tool routing."""
import pytest
from core.agent_session import AgentSession, session_key


def test_session_key_composite():
    key = session_key("task-123", "conv-456")
    assert key == "task-123:conv-456"


def test_session_init():
    session = AgentSession(session_id="test")
    assert session.session_id == "test"
    assert session.containers == []
    assert session.all_tools == []
    assert session.active is False


def test_tool_original_name_mapping():
    session = AgentSession(session_id="test")
    assert session._tool_original_name == {}


@pytest.mark.asyncio
async def test_start_with_no_mcps():
    session = AgentSession(session_id="test")
    tools = await session.start([])
    assert tools == []
    assert session.active is True


@pytest.mark.asyncio
async def test_call_tool_not_found():
    session = AgentSession(session_id="test")
    session.active = True
    result = await session.call_tool("nonexistent", {})
    assert "not found" in result.lower()
