"""
LangGraph Agent Builder - Graph Wiring
=========================================
Wires all 9 nodes into a StateGraph with conditional edges.

Flow:
  N1 (Query Analyzer) → N2 (Similarity Retriever) → N3 (Needs Assessment)
    → [sufficient] → N6 (AI Final Filter)
    → [create_skill] → N4 (Skill Creator) → N5 (Sandbox Validator)
        → [pass] → N6
        → [fail + retries] → N4 (retry)
  N6 → N7 (Docker MCP Runner) → N8 (Template Builder) → N9 (Final Output)
"""
import logging

from langgraph.graph import StateGraph, END

from orchestrator.state import AgentBuilderState
from orchestrator.nodes.query_analyzer import query_analyzer
from orchestrator.nodes.similarity_retriever import similarity_retriever
from orchestrator.nodes.needs_assessment import needs_assessment
from orchestrator.nodes.skill_creator import skill_creator
from orchestrator.nodes.sandbox_validator import sandbox_validator
from orchestrator.nodes.ai_final_filter import ai_final_filter
from orchestrator.nodes.docker_mcp_runner import docker_mcp_runner
from orchestrator.nodes.template_builder import template_builder
from orchestrator.nodes.final_output import final_output

logger = logging.getLogger(__name__)


def _route_after_assessment(state: AgentBuilderState) -> str:
    """Conditional edge after Node 3: create skills or proceed to filter."""
    action = state.get("needs_action", "proceed")
    if action == "create_skill" and state.get("missing_capabilities"):
        logger.info("  → Routing to Skill Creator (missing capabilities)")
        return "skill_creator"
    else:
        logger.info("  → Routing to AI Final Filter (tools sufficient)")
        return "ai_final_filter"


def build_agent_graph() -> StateGraph:
    """
    Build and compile the LangGraph StateGraph with all 9 nodes.

    Returns a compiled graph ready for execution.
    """
    logger.info("🧠 Building Agent Builder LangGraph...")

    # Create the graph
    graph = StateGraph(AgentBuilderState)

    # --- Add all 9 nodes ---
    graph.add_node("query_analyzer", query_analyzer)
    graph.add_node("similarity_retriever", similarity_retriever)
    graph.add_node("needs_assessment", needs_assessment)
    graph.add_node("skill_creator", skill_creator)
    graph.add_node("sandbox_validator", sandbox_validator)
    graph.add_node("ai_final_filter", ai_final_filter)
    graph.add_node("docker_mcp_runner", docker_mcp_runner)
    graph.add_node("template_builder", template_builder)
    graph.add_node("final_output", final_output)

    # --- Set entry point ---
    graph.set_entry_point("query_analyzer")

    # --- Linear edges ---
    graph.add_edge("query_analyzer", "similarity_retriever")
    graph.add_edge("similarity_retriever", "needs_assessment")

    # --- Conditional edge after Needs Assessment ---
    graph.add_conditional_edges(
        "needs_assessment",
        _route_after_assessment,
        {
            "skill_creator": "skill_creator",
            "ai_final_filter": "ai_final_filter",
        },
    )

    # --- Skill creation flow (retry routing TBD; always continue to filter) ---
    graph.add_edge("skill_creator", "sandbox_validator")
    graph.add_edge("sandbox_validator", "ai_final_filter")

    # --- Final pipeline ---
    graph.add_edge("ai_final_filter", "docker_mcp_runner")
    graph.add_edge("docker_mcp_runner", "template_builder")
    graph.add_edge("template_builder", "final_output")
    graph.add_edge("final_output", END)

    # Compile and return
    compiled = graph.compile()
    logger.info("  ✅ Graph compiled successfully")
    return compiled
