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

QUERY_ANALYZER_PROMPT = """You are a Query Expansion Expert. Your job is to break down the user's task into highly specific keywords and sub-queries optimized for a vector database similarity search.

User Task: {user_query}

Instructions:
1. Identify the core capabilities needed (e.g., file reading, web scraping, code execution)
2. Create specific search queries that describe tools and skills needed
3. Include both technical terms and general descriptions
4. Generate 3-8 sub-queries

Output ONLY a valid JSON object with this structure:
{{
    "sub_queries": ["query1", "query2", ...],
    "keywords": ["keyword1", "keyword2", ...],
    "task_category": "security|files|web|data|development|communication|other"
}}"""


async def query_analyzer(state: AgentBuilderState) -> dict:
    """
    Node 1: Analyze and expand the user query into searchable sub-queries.
    """
    user_query = state["user_query"]
    logger.info(f"🔍 Node 1: Analyzing query: {user_query[:100]}...")

    try:
        result = await openrouter_client.chat_completion_json(
            messages=[
                {"role": "system", "content": QUERY_ANALYZER_PROMPT.format(user_query=user_query)},
                {"role": "user", "content": user_query},
            ],
            temperature=0.3,
        )

        sub_queries = result.get("sub_queries", [user_query])
        keywords = result.get("keywords", [])

        # Always include the original query
        if user_query not in sub_queries:
            sub_queries.insert(0, user_query)

        logger.info(f"  Generated {len(sub_queries)} sub-queries")
        return {"sub_queries": sub_queries}

    except Exception as e:
        logger.error(f"Query analyzer failed: {e}")
        return {"sub_queries": [user_query], "errors": state.get("errors", []) + [f"Query analyzer: {str(e)}"]}
