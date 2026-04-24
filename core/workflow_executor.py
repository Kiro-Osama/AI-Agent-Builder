"""
Workflow Executors
===================
Topology-specific execution strategies for multi-agent workflows.
Each executor orchestrates message flow between agents using DeepAgents.

Architecture: Each agent in the workflow is executed via core.deep_agent_runtime
which uses create_deep_agent() with progressive skill disclosure, sandboxing,
and MCP tool integration.
"""
import asyncio
import json
import logging
import re
from typing import Any

from core.deep_agent_runtime import run_deep_agent
from core.mcp_adapter import load_mcp_tools_for_agent
from core.workflow_session import WorkflowSession
from core.workflow_topologies import TopologyType, get_swarm_handoff_instructions

logger = logging.getLogger(__name__)


class WorkflowExecutorResult:
    """Unified result from any topology executor."""

    def __init__(
        self,
        response: str,
        responding_agent: str,
        execution_path: list[str],
        shared_state: dict,
        tool_calls: list[dict] | None = None,
    ):
        self.response = response
        self.responding_agent = responding_agent
        self.execution_path = execution_path
        self.shared_state = shared_state
        self.tool_calls = tool_calls or []

    def to_dict(self) -> dict:
        return {
            "response": self.response,
            "responding_agent": self.responding_agent,
            "execution_path": self.execution_path,
            "shared_state": self.shared_state,
            "tool_calls_count": len(self.tool_calls),
        }


def _extract_balanced_json(text: str, start_idx: int) -> str | None:
    """From first `{` at start_idx, return substring of one balanced {...} or None."""
    depth = 0
    i = start_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx : i + 1]
        i += 1
    return None


def _extract_json_block(text: str) -> dict | None:
    """Try to extract a JSON object from agent response text (handoff / delegation)."""
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Prefer objects that declare handoff / delegation keys (balanced braces)
    for key in ('"handoff_to"', "'handoff_to'", '"delegate_to"', "'delegate_to'"):
        pos = text.find(key)
        if pos == -1:
            continue
        brace = text.rfind("{", 0, pos)
        if brace == -1:
            continue
        blob = _extract_balanced_json(text, brace)
        if not blob:
            continue
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    return None


def _normalize_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _resolve_workflow_role(session: WorkflowSession, raw: str) -> str | None:
    """
    Map LLM output (handoff_to / delegate_to) to a canonical role key in agent_configs.
    Exact match first, then case-insensitive, then slug match on agent_name / role.
    """
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    if raw in session.agent_configs:
        return raw
    lower_map = {k.lower(): k for k in session.agent_configs}
    if raw.lower() in lower_map:
        return lower_map[raw.lower()]
    want = _normalize_key(raw)
    for role, cfg in session.agent_configs.items():
        if _normalize_key(role) == want:
            return role
        name = cfg.get("agent_name") or ""
        if _normalize_key(name) == want:
            return role
    return None


async def _run_single_agent(
    session: WorkflowSession,
    role: str,
    user_message: str,
    extra_context: str = "",
) -> dict:
    """Run one agent's DeepAgent loop and return the result dict."""
    config = session.get_agent_config(role)
    if not config:
        return {"response": f"Error: No config for agent '{role}'", "tool_calls": [], "model": "", "iterations": 0}

    system_prompt = session.get_system_prompt(role)
    if extra_context:
        system_prompt += f"\n\n{extra_context}"

    model = config.get("model", "")
    history = session.get_history(role)

    # Load MCP tools for this agent if it has any
    mcp_tools = None
    selected_mcps = config.get("selected_mcps", [])
    if selected_mcps:
        try:
            mcp_tools = await load_mcp_tools_for_agent(selected_mcps)
        except Exception as e:
            logger.warning("[Workflow] MCP tool loading failed for %s: %s", role, e)

    # Get skill IDs for this agent
    skill_ids = config.get("selected_skills", [])

    result = await run_deep_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        history=history,
        mcp_tools=mcp_tools,
        skill_ids=skill_ids if skill_ids else None,
        model=model or None,
    )

    session.add_to_history(role, {"role": "user", "content": user_message})
    session.add_to_history(role, {"role": "assistant", "content": result.get("response", "")})

    # ----- Memory Layer Integration -----
    # Track turns and store response to memory
    session.increment_turn(role)
    response_text = result.get("response", "")
    if response_text:
        session.store_to_memory(role, f"{role}_last_output", response_text[:2000])

    # Trigger summary compression if threshold hit
    if session.should_summarize(role):
        try:
            await session.summarize_history(role)
        except Exception as e:
            logger.warning("[Workflow] Summary failed for %s: %s", role, e)

    return result


# ============================================================
# Sequential Executor
# ============================================================

async def execute_sequential(
    session: WorkflowSession,
    user_message: str,
) -> WorkflowExecutorResult:
    """
    Run agents in order. Each agent's response becomes input for the next.
    The last agent's response is returned to the user.
    """
    chain = session.routing_rules.get("chain", [])
    if not chain:
        chain = [{"agent": r, "next": None} for r in session.agent_roles]

    execution_path: list[str] = []
    current_message = user_message
    last_result: dict = {}
    all_tool_calls: list[dict] = []

    for i, step in enumerate(chain):
        role = step["agent"]
        execution_path.append(role)
        session.current_agent = role

        context = ""
        if i > 0:
            context = (
                f"## Previous Agent Output\n"
                f"The previous agent in the pipeline produced the following:\n\n"
                f"{current_message}\n\n"
                f"Continue the workflow by processing this input according to your role."
            )

        session.log_message(
            from_agent="user" if i == 0 else chain[i - 1]["agent"],
            to_agent=role,
            message_type="sequential_step",
            content_preview=current_message[:200],
        )

        logger.info("[Sequential] Step %d/%d: agent=%s", i + 1, len(chain), role)

        result = await _run_single_agent(
            session, role,
            user_message if i == 0 else current_message,
            extra_context=context if i > 0 else "",
        )

        response_text = result.get("response", "")
        all_tool_calls.extend(result.get("tool_calls", []))

        # Store output in shared state
        config = session.get_agent_config(role)
        for key in config.get("output_to_shared_state", []):
            session.update_shared_state(role, {key: response_text})

        current_message = response_text
        last_result = result

    return WorkflowExecutorResult(
        response=current_message,
        responding_agent=execution_path[-1] if execution_path else "",
        execution_path=execution_path,
        shared_state=session.shared_state,
        tool_calls=all_tool_calls,
    )


# ============================================================
# Parallel Executor
# ============================================================

async def execute_parallel(
    session: WorkflowSession,
    user_message: str,
) -> WorkflowExecutorResult:
    """
    Run worker agents concurrently, then a merger agent combines results.
    """
    workers = session.routing_rules.get("workers", [])
    merger = session.routing_rules.get("merger")

    if not workers:
        workers = session.agent_roles[:-1] if len(session.agent_roles) > 1 else session.agent_roles
        merger = session.agent_roles[-1] if len(session.agent_roles) > 1 else None

    execution_path: list[str] = []
    all_tool_calls: list[dict] = []

    # Run all workers in parallel
    async def run_worker(role: str):
        session.log_message("user", role, "parallel_dispatch", user_message[:200])
        return role, await _run_single_agent(session, role, user_message)

    logger.info("[Parallel] Dispatching to %d workers: %s", len(workers), workers)
    tasks = [run_worker(r) for r in workers]
    worker_results = await asyncio.gather(*tasks, return_exceptions=True)

    worker_outputs: dict[str, str] = {}
    for item in worker_results:
        if isinstance(item, Exception):
            logger.error("[Parallel] Worker error: %s", item)
            continue
        role, result = item
        execution_path.append(role)
        worker_outputs[role] = result.get("response", "")
        all_tool_calls.extend(result.get("tool_calls", []))
        for key in session.get_agent_config(role).get("output_to_shared_state", []):
            session.update_shared_state(role, {key: worker_outputs[role]})

    # Merge phase
    if merger and merger in session.agent_configs:
        merge_input_parts = []
        for role, output in worker_outputs.items():
            agent_name = session.get_agent_config(role).get("agent_name", role)
            merge_input_parts.append(f"### {agent_name} ({role})\n{output}")
        merge_input = "\n\n---\n\n".join(merge_input_parts)

        merge_context = (
            "## Worker Results\n"
            "The following agents worked in parallel on the user's request. "
            "Synthesize their outputs into a unified, coherent response.\n\n"
            f"{merge_input}"
        )

        session.log_message("workers", merger, "merge", "Combining parallel results")
        execution_path.append(merger)
        session.current_agent = merger

        logger.info("[Parallel] Merging results via: %s", merger)
        merge_result = await _run_single_agent(
            session, merger, user_message, extra_context=merge_context,
        )
        all_tool_calls.extend(merge_result.get("tool_calls", []))

        return WorkflowExecutorResult(
            response=merge_result.get("response", ""),
            responding_agent=merger,
            execution_path=execution_path,
            shared_state=session.shared_state,
            tool_calls=all_tool_calls,
        )

    # No merger — concatenate worker outputs
    combined = "\n\n---\n\n".join(
        f"**{session.get_agent_config(r).get('agent_name', r)}**: {o}"
        for r, o in worker_outputs.items()
    )
    return WorkflowExecutorResult(
        response=combined,
        responding_agent="multiple",
        execution_path=execution_path,
        shared_state=session.shared_state,
        tool_calls=all_tool_calls,
    )


# ============================================================
# Supervisor Executor
# ============================================================

async def execute_supervisor(
    session: WorkflowSession,
    user_message: str,
) -> WorkflowExecutorResult:
    """
    Supervisor receives user message, delegates to workers, reviews, iterates.
    """
    sup_role = session.routing_rules.get("supervisor", session.agent_roles[0])
    workers = session.routing_rules.get("workers", [])
    max_rounds = session.routing_rules.get("max_delegation_rounds", 5)

    execution_path: list[str] = [sup_role]
    all_tool_calls: list[dict] = []
    session.current_agent = sup_role

    current_message = user_message
    worker_reports: list[str] = []

    for round_num in range(1, max_rounds + 1):
        logger.info("[Supervisor] Round %d/%d", round_num, max_rounds)

        # Build context with worker reports from previous rounds
        extra = ""
        if worker_reports:
            extra = "## Worker Reports\n" + "\n\n".join(worker_reports)

        result = await _run_single_agent(
            session, sup_role, current_message, extra_context=extra,
        )
        sup_response = result.get("response", "")
        all_tool_calls.extend(result.get("tool_calls", []))

        # Check if supervisor wants to delegate
        delegation = _extract_json_block(sup_response)
        if delegation and "delegate_to" in delegation:
            raw_worker = delegation["delegate_to"]
            target_role = _resolve_workflow_role(session, str(raw_worker)) or str(raw_worker)
            task_desc = delegation.get("task", current_message)

            if target_role not in workers:
                logger.warning(
                    "[Supervisor] Tried to delegate to unknown worker: %s", target_role
                )
                worker_reports.append(
                    f"Error: Worker '{target_role}' does not exist. Available: {workers}"
                )
                continue

            session.log_delegation(sup_role, target_role, task_desc)
            execution_path.append(target_role)
            session.current_agent = target_role

            logger.info("[Supervisor] Delegating to %s: %s", target_role, task_desc[:100])
            worker_result = await _run_single_agent(
                session, target_role, task_desc,
            )
            worker_response = worker_result.get("response", "")
            all_tool_calls.extend(worker_result.get("tool_calls", []))

            for key in session.get_agent_config(target_role).get("output_to_shared_state", []):
                session.update_shared_state(target_role, {key: worker_response})

            worker_name = session.get_agent_config(target_role).get("agent_name", target_role)
            worker_reports.append(
                f"### Report from {worker_name} ({target_role}):\n{worker_response}"
            )

            session.log_message(target_role, sup_role, "report", worker_response[:200])
            session.current_agent = sup_role
            execution_path.append(sup_role)
            continue

        # No delegation — supervisor produced final answer
        logger.info("[Supervisor] Final answer after %d rounds", round_num)
        return WorkflowExecutorResult(
            response=sup_response,
            responding_agent=sup_role,
            execution_path=execution_path,
            shared_state=session.shared_state,
            tool_calls=all_tool_calls,
        )

    # Max rounds reached — return last supervisor response
    logger.warning("[Supervisor] Max rounds (%d) reached", max_rounds)
    final_msg = (
        f"After {max_rounds} delegation rounds, here is my final synthesis:\n\n"
        + "\n\n".join(worker_reports[-3:])
    )
    return WorkflowExecutorResult(
        response=final_msg,
        responding_agent=sup_role,
        execution_path=execution_path,
        shared_state=session.shared_state,
        tool_calls=all_tool_calls,
    )


# ============================================================
# Swarm Executor
# ============================================================

async def execute_swarm(
    session: WorkflowSession,
    user_message: str,
) -> WorkflowExecutorResult:
    """
    Peer agents can hand off to each other. Current agent decides who handles next.
    """
    initial_agent = session.routing_rules.get("initial_agent", session.agent_roles[0])
    max_handoffs = 8

    current_role = session.current_agent or initial_agent
    execution_path: list[str] = [current_role]
    all_tool_calls: list[dict] = []
    current_message = user_message
    last_response = ""

    for step in range(max_handoffs + 1):
        session.current_agent = current_role

        handoff_instructions = get_swarm_handoff_instructions(
            current_role, session.agent_roles,
        )

        logger.info("[Swarm] Step %d: agent=%s", step, current_role)
        result = await _run_single_agent(
            session, current_role, current_message, extra_context=handoff_instructions,
        )
        response_text = result.get("response", "")
        last_response = response_text
        all_tool_calls.extend(result.get("tool_calls", []))

        for key in session.get_agent_config(current_role).get("output_to_shared_state", []):
            session.update_shared_state(current_role, {key: response_text})

        # Check for handoff
        handoff = _extract_json_block(response_text)
        if handoff and "handoff_to" in handoff:
            raw_target = handoff["handoff_to"]
            reason = str(handoff.get("reason", "") or "")
            target = _resolve_workflow_role(session, str(raw_target))

            if not target:
                logger.warning("[Swarm] Handoff to unknown agent: %s", raw_target)
                return WorkflowExecutorResult(
                    response=response_text,
                    responding_agent=current_role,
                    execution_path=execution_path,
                    shared_state=session.shared_state,
                    tool_calls=all_tool_calls,
                )

            if target == current_role:
                logger.warning("[Swarm] Ignoring self-handoff for %s", current_role)
                return WorkflowExecutorResult(
                    response=response_text,
                    responding_agent=current_role,
                    execution_path=execution_path,
                    shared_state=session.shared_state,
                    tool_calls=all_tool_calls,
                )

            session.log_handoff(current_role, target, reason)
            execution_path.append(target)
            prev_name = session.get_agent_config(current_role).get("agent_name", current_role)
            current_message = (
                f"{user_message}\n\n"
                f"## Routed to you from {prev_name} (`{current_role}`)\n"
                f"Reason: {reason}\n\n"
                f"### Their last message (may include routing metadata)\n{response_text}\n\n"
                "Perform your role for this request. Reply in natural language. "
                "Only use a handoff JSON block if another listed peer must take over."
            )
            current_role = target
            session.current_agent = target
            logger.info("[Swarm] Handoff → %s (reason: %s)", target, reason[:120])
            continue

        # No handoff — return response
        return WorkflowExecutorResult(
            response=response_text,
            responding_agent=current_role,
            execution_path=execution_path,
            shared_state=session.shared_state,
            tool_calls=all_tool_calls,
        )

    logger.warning("[Swarm] Max handoffs (%d) reached", max_handoffs)
    return WorkflowExecutorResult(
        response=(
            f"(Max handoffs reached — last agent may have looped on handoffs.) "
            f"\n\n{last_response}"
        ),
        responding_agent=current_role,
        execution_path=execution_path,
        shared_state=session.shared_state,
        tool_calls=all_tool_calls,
    )


# ============================================================
# Dispatcher — routes to the correct executor
# ============================================================

EXECUTORS = {
    TopologyType.SEQUENTIAL: execute_sequential,
    TopologyType.PARALLEL: execute_parallel,
    TopologyType.SUPERVISOR: execute_supervisor,
    TopologyType.SWARM: execute_swarm,
}


async def execute_workflow(
    session: WorkflowSession,
    user_message: str,
) -> WorkflowExecutorResult:
    """
    Route to the correct topology executor based on the session's topology.
    """
    executor = EXECUTORS.get(session.topology)
    if not executor:
        raise ValueError(f"Unsupported topology: {session.topology}")

    logger.info(
        "[WorkflowExecutor] Executing %s workflow '%s'",
        session.topology.value,
        session.workflow_id,
    )

    return await executor(session, user_message)
