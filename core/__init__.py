"""
Core — Shared libraries used by API and Worker.

Modules:
    models          SQLAlchemy ORM models (BuildHistory, MCP, Skill)
    db              Async database engine and session factory
    openrouter      LLM client: OpenRouter + optional local Ollama (see LLM_PROVIDER / ollama: prefix)
    embeddings      Google Gemini embedding client
    mcp_client      JSON-RPC client for MCP Docker containers
    agent_session   MCP container session manager for chat
    agent_loop      ReAct agent execution loop (LLM ↔ tools)
    docker_manager  Docker SDK wrapper for sandbox execution
"""
