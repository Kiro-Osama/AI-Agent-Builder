"""Tests for API schemas — validation and defaults."""
import pytest
from api.schemas import BuildRequest, BuildResponse, StatusResponse, AgentTemplate


def test_build_request_valid():
    req = BuildRequest(query="Build a file organizer agent")
    assert req.max_mcps == 5
    assert req.enable_skill_creation is True


def test_build_request_too_short():
    with pytest.raises(Exception):
        BuildRequest(query="hi")


def test_build_response_defaults():
    resp = BuildResponse(task_id="abc-123")
    assert resp.status == "queued"


def test_status_response_defaults():
    resp = StatusResponse(task_id="abc-123", status="processing")
    assert resp.progress == 0.0
    assert resp.processing_log == []


def test_agent_template_defaults():
    tmpl = AgentTemplate()
    assert tmpl.project_type == "single_agent"
    assert tmpl.agents == []
