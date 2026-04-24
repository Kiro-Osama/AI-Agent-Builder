"""
Workflow Session Manager
=========================
Manages workflow state for multi-agent DeepAgent workflows.
Handles shared state, inter-agent routing, memory management, and execution logging.

Note: With the DeepAgent migration, this no longer manages MCP containers.
Each agent is stateless; MCP tools are loaded per-call via core.mcp_adapter.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.workflow_topologies import (
    MemoryBackend,
    MemoryConfig,
    MemoryType,
    TopologyType,
)

logger = logging.getLogger(__name__)


class WorkflowSession:
    """
    Manages workflow state for multi-agent DeepAgent workflows.

    With the DeepAgent migration, this no longer manages MCP container sessions.
    Each agent call is stateless — MCP tools are loaded per-call via mcp_adapter.
    This class tracks: configs, conversation history, shared state, memory, execution log.
    """

    def __init__(
        self,
        workflow_id: str,
        topology: str,
        agents: list[dict],
        routing_rules: dict,
        shared_state_schema: dict | None = None,
        mcp_user_configs: dict[str, dict] | None = None,
        memory_config: dict | None = None,
        persisted_memory_state: dict | None = None,
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

        # ----- Memory Layer (NEW) -----
        self.memory_config = MemoryConfig.from_dict(memory_config)
        self.shared_memory: dict[str, Any] = {}       # persistent shared memory pool
        self.private_memory: dict[str, dict] = {}      # per-agent private memory
        self.conversation_summaries: dict[str, str] = {}  # summarized history per agent
        self._turn_counters: dict[str, int] = {}       # track turns for summary triggers

        # Restore persisted memory from previous sessions
        if persisted_memory_state:
            self.shared_memory = persisted_memory_state.get("shared_memory", {})
            self.private_memory = persisted_memory_state.get("private_memory", {})
            self.conversation_summaries = persisted_memory_state.get("conversation_summaries", {})

    @property
    def agent_roles(self) -> list[str]:
        return list(self.agent_configs.keys())

    async def start(self) -> None:
        """Initialize the workflow session (no MCP containers — DeepAgent is stateless)."""
        logger.info(
            "[WorkflowSession:%s] Initializing %d agents (topology=%s, memory=%s/%s)",
            self.workflow_id,
            len(self.agent_configs),
            self.topology.value,
            self.memory_config.memory_type.value,
            self.memory_config.backend.value,
        )

        for role in self.agent_configs:
            self.conversation_history[role] = []
            self.private_memory.setdefault(role, {})
            self._turn_counters.setdefault(role, 0)

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

    # ----- Memory Management (NEW) -----

    def get_effective_memory_config(self, role: str) -> MemoryConfig:
        """Get effective memory config for an agent (agent override → workflow default)."""
        config = self.agent_configs.get(role, {})
        override_dict = config.get("memory_override")
        if override_dict and isinstance(override_dict, dict):
            return MemoryConfig.from_dict(override_dict)
        return self.memory_config

    def store_to_memory(self, role: str, key: str, value: Any) -> None:
        """Route a key-value pair to shared or private memory based on config."""
        mem_cfg = self.get_effective_memory_config(role)

        if mem_cfg.memory_type == MemoryType.PRIVATE:
            self.private_memory.setdefault(role, {})[key] = value
            self._log_event("memory_store", role, None, {
                "scope": "private", "key": key, "preview": str(value)[:200],
            })
        elif mem_cfg.memory_type == MemoryType.HYBRID:
            if key in mem_cfg.private_memory_keys:
                self.private_memory.setdefault(role, {})[key] = value
                self._log_event("memory_store", role, None, {
                    "scope": "private", "key": key, "preview": str(value)[:200],
                })
            else:
                self.shared_memory[key] = value
                self._log_event("memory_store", role, None, {
                    "scope": "shared", "key": key, "preview": str(value)[:200],
                })
        else:  # SHARED
            self.shared_memory[key] = value
            self._log_event("memory_store", role, None, {
                "scope": "shared", "key": key, "preview": str(value)[:200],
            })

    def get_memory_context(self, role: str) -> str:
        """Build memory injection string for an agent's prompt."""
        mem_cfg = self.get_effective_memory_config(role)
        sections: list[str] = []

        # Shared memory (visible to all, or based on hybrid config)
        visible_shared = {}
        if mem_cfg.memory_type in (MemoryType.SHARED, MemoryType.HYBRID):
            if mem_cfg.memory_type == MemoryType.HYBRID and mem_cfg.shared_memory_keys:
                visible_shared = {k: v for k, v in self.shared_memory.items()
                                  if k in mem_cfg.shared_memory_keys}
            else:
                visible_shared = self.shared_memory

        if visible_shared:
            lines = ["## Persistent Shared Memory"]
            for key, value in visible_shared.items():
                val_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                if len(val_str) > 2000:
                    val_str = val_str[:2000] + "... (truncated)"
                lines.append(f"- **{key}**: {val_str}")
            sections.append("\n".join(lines))

        # Private memory (only this agent's)
        priv = self.private_memory.get(role, {})
        if priv:
            lines = ["## Your Private Memory"]
            for key, value in priv.items():
                val_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                if len(val_str) > 2000:
                    val_str = val_str[:2000] + "... (truncated)"
                lines.append(f"- **{key}**: {val_str}")
            sections.append("\n".join(lines))

        # Conversation summary (if backend=summary and a summary exists)
        summary = self.conversation_summaries.get(role)
        if summary:
            sections.append(f"## Previous Conversation Summary\n{summary}")

        return "\n\n".join(sections)

    def increment_turn(self, role: str) -> None:
        """Track turns for summary trigger."""
        self._turn_counters[role] = self._turn_counters.get(role, 0) + 1

    def should_summarize(self, role: str) -> bool:
        """Check if this agent's history should be compressed."""
        mem_cfg = self.get_effective_memory_config(role)
        if mem_cfg.backend != MemoryBackend.SUMMARY:
            return False
        turns = self._turn_counters.get(role, 0)
        return turns > 0 and turns % mem_cfg.summary_interval == 0

    async def summarize_history(self, role: str) -> None:
        """Compress conversation history for an agent using LLM."""
        history = self.conversation_history.get(role, [])
        if len(history) < 4:
            return

        try:
            from core.openrouter import openrouter_client

            history_text = "\n".join(
                f"{msg['role'].upper()}: {msg['content'][:500]}"
                for msg in history[-20:]  # summarize last 20 messages max
            )

            result = await openrouter_client.chat_completion_text(
                messages=[
                    {"role": "system", "content": (
                        "Summarize the following conversation concisely. "
                        "Preserve key decisions, data, and action items. "
                        "Output a brief paragraph summary."
                    )},
                    {"role": "user", "content": history_text},
                ],
                temperature=0.2,
            )

            self.conversation_summaries[role] = result.strip()
            # Trim history to keep only recent messages after summarizing
            mem_cfg = self.get_effective_memory_config(role)
            keep = max(4, mem_cfg.max_history_turns // 2)
            self.conversation_history[role] = history[-keep:]

            logger.info(
                "[WorkflowSession:%s] Summarized history for %s (%d chars)",
                self.workflow_id, role, len(result),
            )
        except Exception as e:
            logger.warning(
                "[WorkflowSession:%s] Failed to summarize history for %s: %s",
                self.workflow_id, role, e,
            )

    def get_memory_state_for_persistence(self) -> dict:
        """Export memory state for DB persistence across sessions."""
        return {
            "shared_memory": self.shared_memory,
            "private_memory": self.private_memory,
            "conversation_summaries": self.conversation_summaries,
        }

    # ----- Existing Methods (unchanged) -----

    def get_agent_config(self, role: str) -> dict:
        return self.agent_configs.get(role, {})

    def get_system_prompt(self, role: str) -> str:
        """Get the system prompt for an agent, injecting shared state and memory context."""
        config = self.agent_configs.get(role, {})
        base_prompt = config.get("system_prompt", "You are a helpful assistant.")

        state_ctx = self._build_shared_state_context(role)
        if state_ctx:
            base_prompt += f"\n\n{state_ctx}"

        # Inject memory context (NEW)
        memory_ctx = self.get_memory_context(role)
        if memory_ctx:
            base_prompt += f"\n\n{memory_ctx}"

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
            "memory_config": self.memory_config.to_dict(),
            "memory_type": self.memory_config.memory_type.value,
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
