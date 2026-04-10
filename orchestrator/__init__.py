"""
Orchestrator — LangGraph pipeline for agent building.

Modules:
    graph       Graph wiring (9 nodes with conditional edges)
    state       AgentBuilderState TypedDict definition

Nodes (orchestrator.nodes):
    query_analyzer       N1 — Break user query into search sub-queries
    similarity_retriever N2 — Semantic search via pgvector
    needs_assessment     N3 — Decide if new skills are needed
    skill_creator        N4 — Generate missing skills dynamically
    sandbox_validator    N5 — Test skills in Docker sandbox
    ai_final_filter      N6 — Select minimal tool set
    docker_mcp_runner    N7 — Prepare MCP container configs
    template_builder     N8 — Assemble final agent JSON template
    final_output         N9 — Validate and finalize
"""
