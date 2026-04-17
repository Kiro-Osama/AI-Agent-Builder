"""
LangGraph State Definition
============================
TypedDict defining the complete graph state passed between nodes.
"""
from typing import Any, TypedDict


class AgentBuilderState(TypedDict):
    """
    Complete state object for the Agent Builder pipeline.
    Each node reads from and writes to specific keys.
    """

    # --- Input ---
    user_query: str                      # Original user request
    preferred_model: str | None          # User's preferred model
    max_mcps: int                        # Max MCPs to select
    max_skills: int                      # Max skills to retrieve for filtering
    enable_skill_creation: bool          # Allow dynamic skill creation
    task_id: str                         # Celery task ID for status updates

    # --- Node 1 Output ---
    sub_queries: list[str]               # Expanded search queries

    # --- Node 2 Output ---
    retrieved_mcps: list[dict]           # Top MCPs from similarity search
    retrieved_skills: list[dict]         # Top Skills from similarity search

    # --- Node 3 Output ---
    missing_capabilities: list[str]      # Capabilities that need new skills
    needs_action: str                    # "proceed" | "create_skill"

    # --- Node 4 Output ---
    new_skills: list[dict]              # Newly created skill definitions

    # --- Node 5 Output ---
    validated_skills: list[dict]         # Skills that passed sandbox testing

    # --- Node 6 Output ---
    selected_tools: dict                 # Final filtered tool selection
    # {
    #   "mcps": [{"mcp_name": "...", "docker_image": "...", ...}],
    #   "skills": [{"skill_id": "...", ...}]
    # }

    # --- Node 7 Output ---
    running_mcps: list[dict]             # Running MCP containers with ports
    # [{"mcp_name": "...", "container_id": "...", "port": 32768}]

    # --- Node 8 & 9 Output ---
    final_template: dict                 # The Dynamic Template JSON

    # --- Pipeline State ---
    status: str                          # Current pipeline status
    errors: list[str]                    # Error accumulator
