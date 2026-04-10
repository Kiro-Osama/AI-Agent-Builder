"""
Node 8: Template Builder
===========================
Assembles the final agent configuration JSON from all gathered components.
Builds exactly ONE agent with the best model, tools, and system prompt.
"""
import json
import logging

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)

TEMPLATE_BUILDER_PROMPT = """You are an Agent Configurator. Build a single-agent execution template as compact JSON.

Task: {user_query}

MCPs available (Docker containers the agent can call):
{running_mcps}

Skills available (knowledge overlays injected into the agent):
{selected_skills}

Rules:
- Build exactly ONE agent that covers the ENTIRE task.
- agent_name: short descriptive name (e.g. "GitHub_Monitor", "Data_Analyst").
- assigned_openrouter_model: pick based on task complexity:
  simple tasks → "meta-llama/llama-3.1-8b-instruct:free"
  medium tasks → "google/gemma-4-26b-a4b-it:free"
  complex tasks → "anthropic/claude-3.5-sonnet"
- selected_mcps: include ONLY MCPs whose tools are directly needed. Use the "name" field from the list above.
- selected_skills: include ALL skill_ids that are relevant to ANY part of the task.
- system_prompt: 3-6 sentences. Describe the agent's role, what tools it has, when to use each tool, and how to approach the task step by step. Be specific — mention tool names and skill capabilities.

Output ONLY this JSON (no markdown, no explanation):
{"project_type":"single_agent","agents":[{"agent_name":"Name","assigned_openrouter_model":"model/id","sub_task":"full task description","selected_mcps":[{"name":"mcp-name","running_port":null}],"selected_skills":["skill-id"],"system_prompt":"Detailed agent instructions."}],"reasoning":"brief reason"}"""


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
        # Build system message via string replacement to avoid .format() breaking
        # on JSON content that contains literal { } characters.
        system_content = (
            TEMPLATE_BUILDER_PROMPT
            .replace("{user_query}", user_query)
            .replace("{running_mcps}", mcps_info)
            .replace("{selected_skills}", skills_info)
        )

        result = await openrouter_client.chat_completion_json(
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Build the agent template for: {user_query}"},
            ],
            temperature=0.3,
            max_tokens=4096,
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

        result["project_type"] = "single_agent"
        if len(result.get("agents", [])) > 1:
            result["agents"] = result["agents"][:1]
            logger.warning("  LLM returned multiple agents — trimmed to first one")

        logger.info(f"  Template: single_agent — {result['agents'][0].get('agent_name', '?')}" if result.get("agents") else "  Template: empty")
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
        
        mcp_names = [m.get("mcp_name", "") for m in full_mcps if m.get("mcp_name")]
        skill_ids = [s["skill_id"] for s in selected_skills]
        tools_note = ""
        if mcp_names:
            tools_note += f" You have access to these MCP tools: {', '.join(mcp_names)}."
        if skill_ids:
            tools_note += f" You are equipped with these skills: {', '.join(skill_ids)}."

        fallback = {
            "project_type": "single_agent",
            "agents": [{
                "agent_name": "AI_Assistant",
                "assigned_openrouter_model": default_model,
                "selected_mcps": full_mcps,
                "selected_skills": skill_ids,
                "system_prompt": (
                    f"You are an AI assistant focused on completing this task: {user_query}."
                    f"{tools_note}"
                    " Analyze the task carefully, use your tools when needed, and provide clear, actionable results."
                ),
                "sub_task": user_query,
            }],
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
