"""
LangSmith / LangChain tracing
==============================
LangChain and LangGraph read ``LANGCHAIN_*`` / ``LANGSMITH_*`` from ``os.environ``.
Pydantic Settings can load values from ``.env`` without exporting them to the
process environment, so the API applies resolved values here at startup.

Workers and the agent-engine call :func:`apply_langsmith_env` after ``load_dotenv``
(or rely on Docker ``env_file``) so Celery tasks and DeepAgent runs trace consistently
under the default project name ``agent_builder``.
"""
from __future__ import annotations

import os

DEFAULT_LANGCHAIN_PROJECT = "agent_builder"
DEFAULT_LANGCHAIN_ENDPOINT = "https://api.smith.langchain.com"


def apply_langsmith_env(
    *,
    langsmith_api_key: str | None = None,
    langchain_project: str | None = None,
    langchain_endpoint: str | None = None,
) -> None:
    """
    Normalize LangSmith-related environment variables.

    If a non-empty API key is found (explicit args, then ``LANGSMITH_API_KEY``,
    then ``LANGCHAIN_API_KEY``), tracing is enabled. Otherwise
    ``LANGCHAIN_TRACING_V2`` defaults to ``false`` when unset.
    """
    key = (
        (langsmith_api_key or "").strip()
        or os.getenv("LANGSMITH_API_KEY", "").strip()
        or os.getenv("LANGCHAIN_API_KEY", "").strip()
    )
    project = (
        (langchain_project or "").strip()
        or os.getenv("LANGCHAIN_PROJECT", "").strip()
        or DEFAULT_LANGCHAIN_PROJECT
    )
    endpoint = (
        (langchain_endpoint or "").strip()
        or os.getenv("LANGCHAIN_ENDPOINT", "").strip()
        or DEFAULT_LANGCHAIN_ENDPOINT
    )

    if key:
        os.environ["LANGSMITH_API_KEY"] = key
        os.environ.setdefault("LANGCHAIN_API_KEY", key)
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = project
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint
    else:
        if "LANGCHAIN_TRACING_V2" not in os.environ:
            os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ.setdefault("LANGCHAIN_PROJECT", project)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", endpoint)
