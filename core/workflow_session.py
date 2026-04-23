"""
Workflow Session Manager
=========================
Manages workflow state for multi-agent DeepAgent workflows.
Handles shared state, inter-agent routing, and execution logging.

Note: With the DeepAgent migration, this no longer manages MCP containers.
Each agent is stateless; MCP tools are loaded per-call via core.mcp_adapter.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.workflow_topologies import TopologyType

logger = logging.getLogger(__name__)


class WorkflowSession:
    """
    Manages workflow state for multi-agent DeepAgent workflows.

    With the DeepAgent migration, this no longer manages MCP container sessions.
    Each agent call is stateless — MCP tools are loaded per-call via mcp_adapter.
    This class tracks: configs, conversation history, shared state, execution log.
    """

    def __init__(
        self,
        workflow_id: str,
        topology: str,
        agents: list[dict],
        routing_rules: dict,
        shared_state_schema: dict | None = None,
        mcp_user_configs: dict[str, dict] | None = None,
    ):
        self.workflow_id = workflow_id
        self.topology = TopologyType(topology)
        self.agent_configs: dict[str, dict] = {a["role"]: a for a in agents}
        self.shared_state: dict[str, Any] = {}
        self.routing_rules = routing_rules or {}
        self.shared_state_schema = shared_state_schema or {}
        self.mcp_user_configs = mcp_user_configs or {}
        self.current_agent: str | None = None
        self.execution_log: list[dict] = []
        self.active = False
        self.created_at = time.time()
        self.conversation_history: dict[str, list[dict]] = {}

    @property
    def agent_roles(self) -> list[str]:
        return list(self.agent_configs.keys())

    async def start(self) -> None:
        """Initialize the workflow session (no MCP containers — DeepAgent is stateless)."""
        logger.info(
            "[WorkflowSession:%s] Initializing %d agents (topology=%s)",
            self.workflow_id,
            len(self.agent_configs),
            self.topology.value,
        )

        for role in self.agent_configs:
            self.conversation_history[role] = []

        # Set initial agent based on topology
        if self.topology == TopologyType.SUPERVISOR:
            sup_role = self.routing_rules.get("supervisor")
            self.current_agent = sup_role or self.agent_roles[0]
        elif self.topology == TopologyType.SWARM:
            self.current_agent = self.routing_rules.get("initial_agent", self.agent_roles[0])
        elif self.topology == TopologyType.SEQUENTIAL:
            chain = self.routing_rules.get("chain", [])
            self.current_agent = chain[0]["agent"] if chain else self.agent_roles[0]
        elif self.topology == TopologyType.PARALLEL:
            self.current_agent = None
        else:
            self.current_agent = self.agent_roles[0] if self.agent_roles else None

        self.active = True
        logger.info(
            "[WorkflowSession:%s] Ready. Initial agent: %s",
            self.workflow_id,
            self.current_agent,
        )

    def get_agent_config(self, role: str) -> dict:
        return self.agent_configs.get(role, {})

    def get_system_prompt(self, role: str) -> str:
        """Get the system prompt for an agent, injecting shared state context."""
        config = self.agent_configs.get(role, {})
        base_prompt = config.get("system_prompt", "You are a helpful assistant.")

        state_ctx = self._build_shared_state_context(role)
        if state_ctx:
            base_prompt += f"\n\n{state_ctx}"

        return base_prompt

    def _build_shared_state_context(self, role: str) -> str:
        """Build shared state injection for an agent's prompt."""
        if not self.shared_state:
            return ""

        config = self.agent_configs.get(role, {})
        reads = config.get("reads_from_shared_state", [])

        relevant = {}
        for key in reads:
            if key in self.shared_state:
                relevant[key] = self.shared_state[key]

        if not relevant and self.shared_state:
            relevant = self.shared_state

        if not relevant:
            return ""

        lines = ["## Shared Workflow State"]
        for key, value in relevant.items():
            val_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            if len(val_str) > 2000:
                val_str = val_str[:2000] + "... (truncated)"
            lines.append(f"- **{key}**: {val_str}")
        return "\n".join(lines)

    def update_shared_state(self, role: str, updates: dict[str, Any]) -> None:
        """Update shared state from an agent's output."""
        for key, value in updates.items():
            self.shared_state[key] = value
            self._log_event("state_update", role, None, {
                "key": key,
                "preview": str(value)[:200],
            })

    def _log_event(
        self,
        event_type: str,
        from_agent: str | None,
        to_agent: str | None,
        data: dict | None = None,
    ):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "data": data or {},
        }
        self.execution_log.append(entry)

    def log_message(self, from_agent: str, to_agent: str | None, message_type: str, content_preview: str = ""):
        self._log_event(message_type, from_agent, to_agent, {"preview": content_preview[:200]})

    def log_delegation(self, from_agent: str, to_agent: str, task: str):
        self._log_event("delegate", from_agent, to_agent, {"task": task})

    def log_handoff(self, from_agent: str, to_agent: str, reason: str):
        self._log_event("handoff", from_agent, to_agent, {"reason": reason})

    def get_history(self, role: str) -> list[dict]:
        return self.conversation_history.get(role, [])

    def add_to_history(self, role: str, message: dict):
        if role not in self.conversation_history:
            self.conversation_history[role] = []
        self.conversation_history[role].append(message)

    async def cleanup(self) -> None:
        """Cleanup workflow session (DeepAgent is stateless, nothing to stop)."""
        logger.info("[WorkflowSession:%s] Cleaning up...", self.workflow_id)
        self.conversation_history.clear()
        self.active = False
        logger.info("[WorkflowSession:%s] Cleanup done", self.workflow_id)

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "topology": self.topology.value,
            "current_agent": self.current_agent,
            "agents": {
                role: {
                    "role": role,
                    "agent_name": cfg.get("agent_name", ""),
                    "skills": cfg.get("selected_skills", []),
                    "mcps_count": len(cfg.get("selected_mcps", [])),
                }
                for role, cfg in self.agent_configs.items()
            },
            "shared_state": self.shared_state,
            "execution_log_count": len(self.execution_log),
        }


# -----------------------------------------------
# Session store (in-memory, keyed by workflow_id:conversation_id)
# -----------------------------------------------
_workflow_sessions: dict[str, WorkflowSession] = {}


def get_workflow_session(key: str) -> WorkflowSession | None:
    return _workflow_sessions.get(key)


def store_workflow_session(key: str, session: WorkflowSession):
    _workflow_sessions[key] = session


async def cleanup_workflow_session(key: str) -> None:
    sess = _workflow_sessions.pop(key, None)
    if sess:
        await sess.cleanup()


async def cleanup_all_workflow_sessions() -> None:
    for key in list(_workflow_sessions.keys()):
        await cleanup_workflow_session(key)
