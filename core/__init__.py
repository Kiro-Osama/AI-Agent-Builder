"""
Core — Shared libraries used by API and Worker.

Modules:
    models              SQLAlchemy ORM models (BuildHistory, MCP, Skill)
    db                  Async database engine and session factory
    deep_agent_runtime  DeepAgent execution engine (replaces legacy agent_loop)
    mcp_adapter         LangChain-native MCP tool loading (replaces legacy mcp_client)
    openrouter          LLM client: OpenRouter + optional local Ollama (used by build pipeline)
    embeddings          Google Gemini embedding client
    docker_manager      Docker SDK wrapper for sandbox execution

Legacy (deprecated — kept for reference):
    _legacy_agent_loop      Old custom ReAct agent loop
    _legacy_agent_session   Old MCP container session manager
    mcp_client              Old JSON-RPC stdio MCP client
"""
