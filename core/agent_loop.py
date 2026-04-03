"""
Agent Loop - ReAct Pattern
============================
Generic agent loop that orchestrates LLM ↔ MCP tool execution.
Works with any MCP, any model, any task.

Flow:
    1. Send system prompt + history + tool definitions to LLM
    2. If LLM returns tool_calls → execute via MCP session → add results → go to 1
    3. If LLM returns text → done
    4. Max iterations to prevent infinite loops
"""
import json
import logging
import os
from typing import Any

from core.openrouter import openrouter_client
from core.agent_session import AgentSession
from core.mcp_client import mcp_tools_to_openrouter

logger = logging.getLogger(__name__)

MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "15"))
DEFAULT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "openrouter/free")


async def run_agent_loop(
    session: AgentSession,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    model: str | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> dict[str, Any]:
    """
    Run the ReAct agent loop.
    
    Args:
        session: AgentSession with running MCP containers
        system_prompt: Agent's system prompt
        history: Previous conversation messages
        user_message: Current user message
        model: OpenRouter model ID (defaults to openrouter/free)
        max_iterations: Safety limit for tool-calling loops

    Returns:
        {
            "response": str,           # Final text response
            "tool_calls": list[dict],   # Log of all tool calls made
            "model": str,              # Model used
            "iterations": int,         # Number of loop iterations
        }
    """
    model = model or DEFAULT_MODEL
    tool_calls_log: list[dict] = []
    
    # Build the tool definitions from MCP session
    openrouter_tools = []
    if session.all_tools:
        openrouter_tools = mcp_tools_to_openrouter(session.all_tools)
        logger.info(
            f"[AgentLoop] {len(openrouter_tools)} tools available: "
            f"{[t['function']['name'] for t in openrouter_tools]}"
        )

    # Enhance system prompt with connected MCP info and path mapping
    enhanced_prompt = system_prompt
    workspace_path = os.getenv("WORKSPACE_PATH", "")
    
    if session.containers:
        mcp_info = session.get_mcp_summary()
        
        # Build path mapping instructions
        path_mapping = ""
        if workspace_path:
            path_mapping = (
                f"\n\n## Path Mapping (CRITICAL)\n"
                f"The host path `{workspace_path}` is mounted as `/workspace` inside the tools.\n"
                f"You MUST convert all host paths to /workspace paths:\n"
                f"- `{workspace_path}` → `/workspace`\n"
                f"- `{workspace_path}AI` → `/workspace/AI`\n"
                f"- `{workspace_path}Downloads` → `/workspace/Downloads`\n"
                f"NEVER use Windows paths like `{workspace_path}...` — always use `/workspace/...`\n"
            )
        
        enhanced_prompt += (
            f"\n\n## Connected Tools\n"
            f"You have the following MCP tools available. USE THEM to complete the task. "
            f"Do NOT make up or imagine results — always call the actual tools.\n\n"
            f"{mcp_info}"
            f"{path_mapping}\n\n"
            f"## Rules\n"
            f"1. ALWAYS call tools to get real data. NEVER fabricate file listings or content.\n"
            f"2. Use `/workspace/...` paths in all tool calls.\n"
            f"3. When a tool returns an error, read the error and adjust your approach.\n"
            f"4. After completing the task, summarize what you actually did with real results."
        )

    # Build initial messages
    messages = [
        {"role": "system", "content": enhanced_prompt},
    ]
    
    # Add conversation history
    for msg in history:
        messages.append(msg)
    
    # Add current user message
    messages.append({"role": "user", "content": user_message})

    # --- ReAct Loop ---
    for iteration in range(1, max_iterations + 1):
        logger.info(f"[AgentLoop] Iteration {iteration}/{max_iterations}")

        try:
            response = await openrouter_client.chat_completion(
                messages=messages,
                model=model,
                tools=openrouter_tools if openrouter_tools else None,
                temperature=0.3,  # Lower temp for tool-using agents
                max_tokens=4096,
            )
        except Exception as e:
            logger.error(f"[AgentLoop] LLM error: {e}")
            return {
                "response": f"Error calling model ({model}): {str(e)}",
                "tool_calls": tool_calls_log,
                "model": model,
                "iterations": iteration,
            }

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        # Check for tool calls
        tool_calls = message.get("tool_calls")

        if tool_calls and finish_reason != "stop":
            # LLM wants to call tools
            logger.info(
                f"[AgentLoop] LLM requested {len(tool_calls)} tool call(s)"
            )

            # Add the assistant message (with tool_calls) to history
            messages.append(message)

            for tool_call in tool_calls:
                fn = tool_call.get("function", {})
                tool_name = fn.get("name", "")
                
                # Parse arguments
                try:
                    arguments = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                
                tool_call_id = tool_call.get("id", f"call_{iteration}")

                logger.info(f"[AgentLoop] 🔧 {tool_name}({json.dumps(arguments)[:150]})")

                # Execute tool via MCP session
                try:
                    result = await session.call_tool(tool_name, arguments)
                    # Truncate very long results to prevent context overflow
                    if len(result) > 10000:
                        result = result[:10000] + f"\n\n... (truncated, {len(result)} total chars)"
                except Exception as e:
                    result = f"Tool execution error: {str(e)}"

                # Log the tool call
                tool_calls_log.append({
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": arguments,
                    "result": result[:500],  # Truncated for the log
                    "success": not result.startswith("Error"),
                })

                logger.info(f"[AgentLoop] 📋 Result: {result[:200]}...")

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                })

            # Continue the loop - let the LLM process tool results
            continue

        else:
            # LLM returned a final text response (no tool calls)
            final_response = message.get("content", "")
            
            if not final_response:
                final_response = "(Agent returned empty response)"

            logger.info(
                f"[AgentLoop] ✅ Final response after {iteration} iteration(s), "
                f"{len(tool_calls_log)} tool call(s)"
            )

            return {
                "response": final_response,
                "tool_calls": tool_calls_log,
                "model": model,
                "iterations": iteration,
            }

    # Max iterations reached
    logger.warning(f"[AgentLoop] Hit max iterations ({max_iterations})")
    last_content = messages[-1].get("content", "") if messages else ""
    
    return {
        "response": (
            f"I've used {len(tool_calls_log)} tools across {max_iterations} steps. "
            f"Here's where I got to:\n\n{last_content}"
        ),
        "tool_calls": tool_calls_log,
        "model": model,
        "iterations": max_iterations,
    }
