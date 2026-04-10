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

QUERY_ANALYZER_PROMPT = """Break down this task into 3-6 short search queries for a vector database that stores tools (MCPs) and skills.
Focus on capabilities needed: what tools, APIs, services, or knowledge domains.

Task: {user_query}

Output ONLY JSON: {{"sub_queries":["query1","query2"],"keywords":["kw1","kw2"]}}"""


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
            max_tokens=512,
        )

        sub_queries = result.get("sub_queries", [user_query])

        if user_query not in sub_queries:
            sub_queries.insert(0, user_query)

        logger.info("  Generated %d sub-queries", len(sub_queries))
        return {"sub_queries": sub_queries}

    except Exception as e:
        logger.error("Query analyzer failed: %s", e)
        return {"sub_queries": [user_query], "errors": state.get("errors", []) + [f"Query analyzer: {str(e)}"]}
