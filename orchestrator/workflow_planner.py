"""
Workflow Planner
=================
LLM-powered task decomposition, topology selection, and agent role design.
Receives a complex user query, returns a WorkflowPlan describing the
multi-agent workflow to build.
"""
import json
import logging
import os
import re
from typing import Any

from core.openrouter import openrouter_client
from core.workflow_topologies import (
    AgentRole,
    MemoryConfig,
    TopologyType,
    WorkflowPlan,
    build_routing_rules,
    build_shared_state_schema,
)

logger = logging.getLogger(__name__)

PLANNER_MODEL = os.getenv(
    "WORKFLOW_PLANNER_MODEL", "google/gemma-4-26b-a4b-it:free"
)

PLANNER_SYSTEM_PROMPT = """\
You are an expert multi-agent workflow planner. Given a complex task description,
you decompose it into sub-agents and select the best execution topology.

## Supported Topologies

### sequential
Agents run one after another; output of agent N becomes input for agent N+1.
Use when tasks have clear linear dependencies (research -> analyze -> write).

### parallel
Multiple agents work independently on different sub-tasks, then a final merger
agent combines the results. Use when sub-tasks are independent and can run
concurrently (audit frontend + backend + security simultaneously).

### supervisor
A supervisor agent delegates tasks to worker agents, reviews their output,
and iterates if needed. Use when tasks need iterative quality control
(build code -> test -> review -> refine).

### swarm
Agents are peers that can hand off to each other based on conversation context.
No fixed ordering. Use for dynamic conversational routing
(sales -> support -> billing based on user needs).

## Output Format

Respond with ONLY a JSON object (no markdown, no explanation):

{
  "workflow_name": "Human-Readable Workflow Name",
  "topology": "sequential|parallel|supervisor|swarm",
  "agents": [
    {
      "role": "unique_role_id",
      "agent_name": "Human_Agent_Name",
      "sub_task": "Clear description of what this agent does",
      "needs_mcps": ["mcp capability hints for the builder"],
      "needs_skills": ["skill capability hints for the builder"],
      "depends_on": ["role_id of agents this depends on"],
      "output_to_shared_state": ["key names this agent produces"],
      "reads_from_shared_state": ["key names this agent consumes"]
    }
  ],
  "supervisor_config": {
    "supervisor_role": "role_id"
  },
  "termination_condition": "all_agents_complete|supervisor_decides|no_handoff",
  "reasoning": "Brief explanation of why this topology was chosen"
}

## Memory Strategy
You must also decide the memory strategy for the workflow.

### Memory Types
- **shared**: All agents read/write a single shared memory (best for sequential pipelines where each agent builds on the previous output).
- **private**: Each agent has its own isolated memory (best for parallel workers that don't need to see each other's internal state).
- **hybrid**: Mix of shared keys (visible to all) and private keys (agent-specific). Best for supervisor/swarm where the supervisor needs visibility but workers keep internal notes.

### Memory Backends
- **conversation**: Keep raw message history (default, good for most workflows).
- **summary**: Periodically compress conversation into summaries (good for long-running agents that accumulate many turns).
- **kv_store**: Structured key-value extraction (good for data processing pipelines that produce structured outputs).

Include in your JSON output:
{
  ...
  "memory_strategy": {
    "memory_type": "shared|private|hybrid",
    "backend": "conversation|summary|kv_store",
    "max_history_turns": 20,
    "reasoning": "Why this memory configuration suits the workflow"
  }
}

Agents may optionally include a "memory_override" object if they need a different config than the workflow default:
{
  ...
  "memory_override": {
    "backend": "summary",
    "private_memory_keys": ["internal_notes"]
  }
}

## Rules
1. Each agent must have a unique role ID (lowercase_snake_case).
2. For supervisor topology, include the supervisor as the first agent.
3. For swarm topology, do NOT include a supervisor — all agents are peers.
4. For parallel topology, add a merger agent as the last agent.
5. Keep agent count between 2 and 6 for efficiency.
6. The sub_task must be specific enough to build a focused single agent.
7. needs_mcps and needs_skills are HINTS — the builder pipeline will find the best matches.
8. Always include a memory_strategy block — choose the best memory type for the selected topology.
"""


def _robust_json_parse(text: Any) -> dict:
    """Try multiple strategies to extract JSON from LLM response."""
    if isinstance(text, list):
        text = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in text])
    elif not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from planner output: {text[:300]}")


async def plan_workflow(user_query: str, topology_hint: str | None = None) -> WorkflowPlan:
    """
    Call the LLM to decompose a user query into a multi-agent workflow plan.

    Args:
        user_query: The complex task description from the user.
        topology_hint: Optional topology preference ("auto" or a specific type).

    Returns:
        WorkflowPlan dataclass with all agent roles and routing config.
    """
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Task: {user_query}"
                + (f"\n\nPreferred topology: {topology_hint}" if topology_hint and topology_hint != "auto" else "")
            ),
        },
    ]

    logger.info("[WorkflowPlanner] Planning workflow for: %s", user_query[:120])

    response = await openrouter_client.chat_completion(
        messages=messages,
        model=PLANNER_MODEL,
        temperature=0.4,
        max_tokens=4096,
    )

    raw_content = (
        response.get("choices", [{}])[0].get("message", {}).get("content", "")
    )
    logger.info("[WorkflowPlanner] Raw planner output: %s", raw_content[:500])

    parsed = _robust_json_parse(raw_content)

    topology_str = parsed.get("topology", "sequential").lower()
    try:
        topology = TopologyType(topology_str)
    except ValueError:
        logger.warning(
            "[WorkflowPlanner] Unknown topology '%s', falling back to sequential",
            topology_str,
        )
        topology = TopologyType.SEQUENTIAL

    # Parse workflow-level memory strategy
    memory_strategy = MemoryConfig.from_dict(parsed.get("memory_strategy"))
    logger.info(
        "[WorkflowPlanner] Memory strategy: type=%s, backend=%s",
        memory_strategy.memory_type.value,
        memory_strategy.backend.value,
    )

    agents: list[AgentRole] = []
    for a in parsed.get("agents", []):
        # Parse optional per-agent memory override
        agent_mem_override = None
        if a.get("memory_override"):
            agent_mem_override = MemoryConfig.from_dict(a["memory_override"])

        agents.append(
            AgentRole(
                role=a.get("role", "agent"),
                agent_name=a.get("agent_name", "Agent"),
                sub_task=a.get("sub_task", ""),
                needs_mcps=a.get("needs_mcps", []),
                needs_skills=a.get("needs_skills", []),
                depends_on=a.get("depends_on", []),
                reads_from_shared_state=a.get("reads_from_shared_state", []),
                output_to_shared_state=a.get("output_to_shared_state", []),
                memory_override=agent_mem_override,
            )
        )

    if not agents:
        raise ValueError("Planner returned no agents")

    # Wire up topology-specific fields
    all_roles = [a.role for a in agents]
    if topology == TopologyType.SUPERVISOR:
        sup_cfg = parsed.get("supervisor_config") or {}
        sup_role = sup_cfg.get("supervisor_role", agents[0].role)
        for a in agents:
            if a.role == sup_role:
                a.accepts_from = ["user"]
                a.reports_to = ["user"]
            else:
                a.accepts_from = [sup_role]
                a.reports_to = [sup_role]
    elif topology == TopologyType.SWARM:
        for a in agents:
            a.accepts_from = [r for r in all_roles if r != a.role]
            a.reports_to = [r for r in all_roles if r != a.role]

    routing_rules = build_routing_rules(topology, agents)
    shared_schema = build_shared_state_schema(agents)

    plan = WorkflowPlan(
        workflow_name=parsed.get("workflow_name", "Untitled Workflow"),
        topology=topology,
        agents=agents,
        supervisor_config=parsed.get("supervisor_config"),
        termination_condition=parsed.get("termination_condition", "all_agents_complete"),
        shared_state_schema=shared_schema,
        routing_rules=routing_rules,
        reasoning=parsed.get("reasoning", ""),
        memory_strategy=memory_strategy,
    )

    logger.info(
        "[WorkflowPlanner] Plan: %s | topology=%s | %d agents",
        plan.workflow_name,
        plan.topology.value,
        len(plan.agents),
    )

    return plan
