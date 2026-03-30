"""
Node 8: Template Builder
===========================
Assembles the final Dynamic Template JSON from all gathered components.
Determines single-agent vs multi-agent, picks the best model, writes system prompt.
"""
import json
import logging

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)

TEMPLATE_BUILDER_PROMPT = """You are the Agent Configurator for an Agent Builder system. Assemble the final execution template.

Task: {user_query}

Selected Running MCPs (with active Docker ports):
{running_mcps}

Selected Skills (active and validated):
{selected_skills}

Instructions:
1. Determine if this task requires a Multi-Agent System (MAS). If the task has clearly distinct sub-tasks (e.g., read + analyze + report), split into multiple agents. For simpler tasks, use a single agent.
2. Choose the best OpenRouter model for each agent based on task complexity:
   - Simple tasks: "meta-llama/llama-3.1-8b-instruct"
   - Medium tasks: "anthropic/claude-3.5-sonnet"
   - Complex/Creative: "openai/gpt-4o"
3. Write a comprehensive system prompt for each agent, specifically mentioning:
   - The exact running ports of the MCPs
   - The available skills and their capabilities
   - Clear instructions on how to use each tool
4. Give each agent a descriptive name.

Output ONLY valid JSON:
{{
    "project_type": "single_agent" | "multi_agent",
    "agents": [
        {{
            "agent_name": "Descriptive_Agent_Name",
            "assigned_openrouter_model": "model/id",
            "sub_task": "What this specific agent handles",
            "selected_mcps": [
                {{"name": "mcp-name", "running_port": 12345}}
            ],
            "selected_skills": ["skill-id-1"],
            "system_prompt": "You are a specialized agent..."
        }}
    ],
    "execution_order": "sequential" | "parallel",
    "reasoning": "Why this configuration was chosen"
}}"""


async def template_builder(state: AgentBuilderState) -> dict:
    """
    Node 8: Build the final Dynamic Template.
    """
    user_query = state["user_query"]
    running_mcps = state.get("running_mcps", [])
    selected_tools = state.get("selected_tools", {})
    selected_skills = selected_tools.get("skills", [])
    preferred_model = state.get("preferred_model")

    logger.info("📋 Node 8: Building final template...")

    # Format running MCPs info
    mcps_info = json.dumps([
        {
            "name": m["mcp_name"],
            "running_port": m.get("running_port"),
            "tools": m.get("tools_provided", []),
            "status": m.get("status", "unknown"),
        }
        for m in running_mcps
        if m.get("status") != "failed"
    ], indent=2)

    skills_info = json.dumps([
        {
            "skill_id": s["skill_id"],
            "name": s.get("skill_name", s["skill_id"]),
            "description": s.get("description", ""),
            "tools": s.get("skill_data", {}).get("tools_schema", []) if isinstance(s.get("skill_data"), dict) else [],
        }
        for s in selected_skills
    ], indent=2) if selected_skills else "[]"

    try:
        result = await openrouter_client.chat_completion_json(
            messages=[
                {
                    "role": "system",
                    "content": TEMPLATE_BUILDER_PROMPT.format(
                        user_query=user_query,
                        running_mcps=mcps_info,
                        selected_skills=skills_info,
                    ),
                },
                {
                    "role": "user",
                    "content": f"Build the agent template for: {user_query}",
                },
            ],
            temperature=0.3,
        )

        # Override model if user specified preference
        if preferred_model:
            for agent in result.get("agents", []):
                agent["assigned_openrouter_model"] = preferred_model

        # Add status
        result["status"] = "ready_for_user_approval"

        logger.info(f"  Template: {result.get('project_type')} with {len(result.get('agents', []))} agent(s)")
        return {"final_template": result}

    except Exception as e:
        logger.error(f"Template builder failed: {e}")
        # Build a fallback template using FREE model
        import os
        default_model = preferred_model or os.getenv("DEFAULT_CHAT_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        fallback = {
            "project_type": "single_agent",
            "agents": [{
                "agent_name": "AI_Assistant",
                "assigned_openrouter_model": default_model,
                "selected_mcps": [
                    {"name": m["mcp_name"], "running_port": m.get("running_port")}
                    for m in running_mcps if m.get("status") != "failed"
                ],
                "selected_skills": [s["skill_id"] for s in selected_skills],
                "system_prompt": f"You are a highly capable AI assistant. Your task: {user_query}\n\nYou have access to the following tools and should use them to complete the task effectively.",
                "sub_task": user_query,
            }],
            "execution_order": "sequential",
            "status": "ready_for_user_approval",
            "warning": f"Template built with fallback due to error: {str(e)}",
        }
        return {
            "final_template": fallback,
            "errors": state.get("errors", []) + [f"Template builder: {str(e)}"],
        }
