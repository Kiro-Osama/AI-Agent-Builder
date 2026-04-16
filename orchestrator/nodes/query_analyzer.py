"""
Node 1: Query Analyzer
========================
Breaks down the user's task into specific keywords and sub-queries
for vector database similarity search.
"""
import json
import logging

from orchestrator.state import AgentBuilderState
from core.openrouter import openrouter_client

logger = logging.getLogger(__name__)

QUERY_ANALYZER_PROMPT = """You write search text for TWO vector indexes in one database:
(1) MCPs — runnable tool servers (filesystem, git, APIs, browser, DBs, issue trackers, Docker…)
(2) Skills — knowledge playbooks (docs, PDF, slides, templates, comms, writing, internal procedures…)

User task:
{user_query}

Rules:
- `sub_queries` MUST have at least 2 strings, in this order:
  - sub_queries[0]: Short English (or mixed) text optimized to FIND MCPs / external tools for this task.
  - sub_queries[1]: Short text optimized to FIND SKILLS / document & knowledge assets for this task (can mention docx, pdf, pptx, playbooks if relevant).
- Optionally add sub_queries[2..] with extra angles (still short).
- `keywords`: 4-8 tokens for logging.

Output ONLY JSON: {{"sub_queries":["mcp-focused…","skills-focused…"],"keywords":["…"]}}"""


async def query_analyzer(state: AgentBuilderState) -> dict:
    """
    Node 1: Analyze and expand the user query into searchable sub-queries.
    """
    user_query = state["user_query"]
    logger.info("🔍 Node 1: Analyzing query: %s...", user_query[:100])

    try:
        result = await openrouter_client.chat_completion_json(
            messages=[
                {"role": "system", "content": QUERY_ANALYZER_PROMPT.format(user_query=user_query)},
                {"role": "user", "content": user_query},
            ],
            temperature=0.3,
            max_tokens=1024,
        )

        raw = result.get("sub_queries") or []
        sub_queries = [str(s).strip() for s in raw if s and str(s).strip()]
        if not sub_queries:
            sub_queries = [user_query.strip() or user_query]
        # Guarantee MCP vs skills channels for the retriever (dual embedding)
        if len(sub_queries) == 1:
            u = sub_queries[0]
            sub_queries = [
                f"{u} MCP tools APIs filesystem git docker automation",
                f"{u} skills documentation templates playbooks knowledge PDF docx",
            ]
            logger.info("  LLM returned one line — split into MCP- vs skills-oriented search text")
        # Keep verbatim user task inside MCP-oriented line if not already present
        uq = (user_query or "").strip()
        if uq and uq.lower() not in sub_queries[0].lower():
            sub_queries[0] = f"{uq} | {sub_queries[0]}"

        logger.info("  Generated %d sub-queries", len(sub_queries))
        return {"sub_queries": sub_queries}

    except Exception as e:
        logger.error("Query analyzer failed: %s", e)
        return {"sub_queries": [user_query], "errors": state.get("errors", []) + [f"Query analyzer: {str(e)}"]}
