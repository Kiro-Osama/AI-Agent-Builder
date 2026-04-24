"""
Workflow Topologies
====================
Definitions, routing logic, and shared state schemas for each
supported multi-agent workflow topology.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TopologyType(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    SUPERVISOR = "supervisor"
    SWARM = "swarm"


class MemoryType(str, Enum):
    """How memory is scoped across agents in a workflow."""
    SHARED = "shared"       # All agents read/write one shared memory store
    PRIVATE = "private"     # Each agent has its own isolated memory
    HYBRID = "hybrid"       # Some keys shared, some private per-agent


class MemoryBackend(str, Enum):
    """How conversation history is stored / compressed."""
    CONVERSATION = "conversation"   # Raw message history (default)
    SUMMARY = "summary"             # LLM-summarized memory (compresses long histories)
    KV_STORE = "kv_store"           # Structured key-value store (data extraction pipelines)


@dataclass
class MemoryConfig:
    """Memory strategy configuration for a workflow or individual agent."""
    memory_type: MemoryType = MemoryType.SHARED
    backend: MemoryBackend = MemoryBackend.CONVERSATION
    max_history_turns: int = 20
    summary_interval: int = 10       # summarize every N turns when backend=summary
    shared_memory_keys: list[str] = field(default_factory=list)
    private_memory_keys: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "memory_type": self.memory_type.value,
            "backend": self.backend.value,
            "max_history_turns": self.max_history_turns,
            "summary_interval": self.summary_interval,
            "shared_memory_keys": self.shared_memory_keys,
            "private_memory_keys": self.private_memory_keys,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> MemoryConfig:
        if not d:
            return cls()
        try:
            mt = MemoryType(d.get("memory_type", "shared"))
        except ValueError:
            mt = MemoryType.SHARED
        try:
            mb = MemoryBackend(d.get("backend", "conversation"))
        except ValueError:
            mb = MemoryBackend.CONVERSATION
        return cls(
            memory_type=mt,
            backend=mb,
            max_history_turns=int(d.get("max_history_turns", 20)),
            summary_interval=int(d.get("summary_interval", 10)),
            shared_memory_keys=list(d.get("shared_memory_keys") or []),
            private_memory_keys=list(d.get("private_memory_keys") or []),
            reasoning=str(d.get("reasoning", "")),
        )


@dataclass
class AgentRole:
    role: str
    agent_name: str
    sub_task: str
    task_id: str | None = None
    needs_mcps: list[str] = field(default_factory=list)
    needs_skills: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    accepts_from: list[str] = field(default_factory=list)
    reports_to: list[str] = field(default_factory=list)
    reads_from_shared_state: list[str] = field(default_factory=list)
    output_to_shared_state: list[str] = field(default_factory=list)
    result_template: dict | None = None
    memory_override: MemoryConfig | None = None  # per-agent override of workflow default

    def to_dict(self) -> dict:
        d = {
            "role": self.role,
            "agent_name": self.agent_name,
            "sub_task": self.sub_task,
            "task_id": self.task_id,
            "needs_mcps": self.needs_mcps,
            "needs_skills": self.needs_skills,
            "depends_on": self.depends_on,
            "accepts_from": self.accepts_from,
            "reports_to": self.reports_to,
            "reads_from_shared_state": self.reads_from_shared_state,
            "output_to_shared_state": self.output_to_shared_state,
        }
        if self.memory_override:
            d["memory_override"] = self.memory_override.to_dict()
        return d


@dataclass
class WorkflowPlan:
    workflow_name: str
    topology: TopologyType
    agents: list[AgentRole]
    supervisor_config: dict | None = None
    termination_condition: str = "all_agents_complete"
    shared_state_schema: dict = field(default_factory=dict)
    routing_rules: dict = field(default_factory=dict)
    reasoning: str = ""
    memory_strategy: MemoryConfig = field(default_factory=MemoryConfig)  # workflow-level default

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "topology": self.topology.value,
            "agents": [a.to_dict() for a in self.agents],
            "supervisor_config": self.supervisor_config,
            "termination_condition": self.termination_condition,
            "shared_state_schema": self.shared_state_schema,
            "routing_rules": self.routing_rules,
            "reasoning": self.reasoning,
            "memory_strategy": self.memory_strategy.to_dict(),
        }


def build_routing_rules(topology: TopologyType, agents: list[AgentRole]) -> dict:
    """Build topology-specific routing rules from the agent list."""
    roles = [a.role for a in agents]

    if topology == TopologyType.SEQUENTIAL:
        chain = []
        for i, agent in enumerate(agents):
            chain.append({
                "agent": agent.role,
                "next": agents[i + 1].role if i + 1 < len(agents) else None,
            })
        return {
            "type": "sequential",
            "chain": chain,
            "termination": "last_agent_complete",
        }

    if topology == TopologyType.PARALLEL:
        return {
            "type": "parallel",
            "workers": roles[:-1] if len(roles) > 1 else roles,
            "merger": roles[-1] if len(roles) > 1 else None,
            "termination": "all_workers_complete",
        }

    if topology == TopologyType.SUPERVISOR:
        supervisor = None
        workers = []
        for a in agents:
            if "supervisor" in a.role.lower() or "manager" in a.role.lower():
                supervisor = a.role
            else:
                workers.append(a.role)
        if not supervisor and agents:
            supervisor = agents[0].role
            workers = roles[1:]
        return {
            "type": "supervisor",
            "supervisor": supervisor,
            "workers": workers,
            "max_delegation_rounds": 5,
            "termination": "supervisor_decides",
        }

    if topology == TopologyType.SWARM:
        handoff_map = {a.role: [r for r in roles if r != a.role] for a in agents}
        return {
            "type": "swarm",
            "handoff_map": handoff_map,
            "initial_agent": roles[0] if roles else None,
            "termination": "no_handoff",
        }

    return {"type": topology.value}


def build_shared_state_schema(agents: list[AgentRole]) -> dict:
    """Derive a shared state schema from agents' declared state keys."""
    schema: dict[str, str] = {}
    for agent in agents:
        for key in agent.output_to_shared_state:
            schema[key] = "any"
    return schema


def get_supervisor_system_prompt(
    supervisor_name: str,
    workers: list[AgentRole],
    workflow_name: str,
) -> str:
    """Build a system prompt for a supervisor agent that knows about its workers."""
    worker_descriptions = "\n".join(
        f"- **{w.agent_name}** (role: {w.role}): {w.sub_task}"
        for w in workers
    )
    return (
        f"You are {supervisor_name}, the supervisor of the '{workflow_name}' workflow.\n\n"
        f"## Your Workers\n{worker_descriptions}\n\n"
        "## Your Responsibilities\n"
        "1. Receive the user's request and break it into sub-tasks.\n"
        "2. Delegate sub-tasks to the appropriate worker by responding with a JSON block:\n"
        '   ```json\n   {"delegate_to": "<role>", "task": "<specific instruction>"}\n   ```\n'
        "3. Review each worker's response. If quality is insufficient, re-delegate with feedback.\n"
        "4. Once all sub-tasks are satisfied, synthesize a final answer for the user.\n"
        "5. When done, respond with your final answer (no delegation block).\n\n"
        "## Rules\n"
        "- Only delegate to workers listed above.\n"
        "- Maximum 5 delegation rounds before you must produce a final answer.\n"
        "- Always explain your reasoning before delegating.\n"
    )


def get_swarm_handoff_instructions(agent_role: str, all_roles: list[str]) -> str:
    """Build instructions enabling an agent to hand off to peers."""
    peers = [r for r in all_roles if r != agent_role]
    if not peers:
        return ""
    peer_list = ", ".join(peers)
    return (
        "\n\n## Handoff Protocol\n"
        f"You can hand off the conversation to a peer agent if the user's request "
        f"is better handled by them. Available peer **role** ids (use these exact strings "
        f"for `handoff_to`, case-sensitive): {peer_list}\n"
        "To hand off, respond with ONLY a JSON block:\n"
        '```json\n{"handoff_to": "<role>", "reason": "<why>"}\n```\n'
        "If you can handle the request yourself, respond normally (no handoff block).\n"
        "Never hand off to yourself. Never emit a handoff block after you have already "
        "done your specialist work — use handoff only to switch agents, not as a substitute "
        "for your report.\n"
    )
