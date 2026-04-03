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

        # ---- CRITICAL: Inject full MCP metadata ----
        # The LLM template only has {name, running_port} for MCPs.
        # We need to inject docker_image, run_config, tools_provided
        # from the pipeline state so the chat system can start containers.
        _inject_mcp_metadata(result, running_mcps, selected_tools.get("mcps", []))

        # Add status
        result["status"] = "ready_for_user_approval"

        logger.info(f"  Template: {result.get('project_type')} with {len(result.get('agents', []))} agent(s)")
        return {"final_template": result}

    except Exception as e:
        logger.error(f"Template builder failed: {e}")
        # Build a fallback template using FREE model
        import os
        default_model = preferred_model or os.getenv("DEFAULT_CHAT_MODEL", "openrouter/free")
        
        # Build full MCP entries for the fallback
        all_mcps = running_mcps + selected_tools.get("mcps", [])
        full_mcps = []
        seen = set()
        for m in all_mcps:
            name = m.get("mcp_name", "")
            if name not in seen and m.get("docker_image"):
                seen.add(name)
                full_mcps.append({
                    "mcp_name": name,
                    "docker_image": m["docker_image"],
                    "run_config": m.get("run_config", {}),
                    "tools_provided": m.get("tools_provided", []),
                })
        
        fallback = {
            "project_type": "single_agent",
            "agents": [{
                "agent_name": "AI_Assistant",
                "assigned_openrouter_model": default_model,
                "selected_mcps": full_mcps,
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


def _inject_mcp_metadata(template: dict, running_mcps: list, selected_mcps: list) -> None:
    """
    Inject full MCP metadata (docker_image, run_config, tools_provided) into 
    agents' selected_mcps. The LLM only outputs {name, running_port} so we
    need to merge in the real data from the pipeline state.
    """
    # Build a lookup map: mcp_name → full metadata
    mcp_lookup: dict[str, dict] = {}
    
    for m in selected_mcps:
        name = m.get("mcp_name", "")
        if name and m.get("docker_image"):
            mcp_lookup[name] = {
                "mcp_name": name,
                "docker_image": m["docker_image"],
                "run_config": m.get("run_config", {}),
                "tools_provided": m.get("tools_provided", []),
                "default_ports": m.get("default_ports", []),
                "category": m.get("category", ""),
            }
    
    for m in running_mcps:
        name = m.get("mcp_name", "")
        if name:
            if name not in mcp_lookup:
                mcp_lookup[name] = {}
            mcp_lookup[name].update({
                "mcp_name": name,
                "docker_image": m.get("docker_image", mcp_lookup.get(name, {}).get("docker_image", "")),
                "run_config": m.get("run_config", mcp_lookup.get(name, {}).get("run_config", {})),
                "tools_provided": m.get("tools_provided", mcp_lookup.get(name, {}).get("tools_provided", [])),
                "container_id": m.get("container_id"),
                "running_port": m.get("running_port"),
                "transport": m.get("transport", "stdio"),
            })

    # Now enrich each agent's selected_mcps
    for agent in template.get("agents", []):
        raw_mcps = agent.get("selected_mcps", [])
        enriched = []
        
        for mcp_entry in raw_mcps:
            # The LLM may output {name, running_port} or {mcp_name, ...}
            name = mcp_entry.get("name") or mcp_entry.get("mcp_name", "")
            
            if name in mcp_lookup:
                # Merge LLM data with actual metadata
                full = dict(mcp_lookup[name])
                full.update({k: v for k, v in mcp_entry.items() if v is not None})
                full["mcp_name"] = name  # Normalize key
                enriched.append(full)
            else:
                # MCP not in lookup — keep as-is but log warning
                logger.warning(f"  MCP '{name}' from LLM template not found in pipeline state")
                mcp_entry["mcp_name"] = name
                enriched.append(mcp_entry)
        
        # If LLM didn't include any MCPs but we have them, add all
        if not enriched and mcp_lookup:
            logger.info("  LLM template had no MCPs, injecting all from pipeline")
            enriched = list(mcp_lookup.values())
        
        agent["selected_mcps"] = enriched
