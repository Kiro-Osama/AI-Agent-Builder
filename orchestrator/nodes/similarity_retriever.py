"""
Node 2: Similarity Retriever
==============================
Performs semantic search on MCPs and Skills tables using pgvector.
Returns top-N results by cosine similarity.
"""
import logging
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from orchestrator.state import AgentBuilderState
from core.embeddings import embedding_generator

logger = logging.getLogger(__name__)

import os

_SYNC_DB_URL = os.getenv("ALEMBIC_DATABASE_URL", "").strip()
if not _SYNC_DB_URL:
    raise RuntimeError(
        "ALEMBIC_DATABASE_URL is required for the LangGraph pipeline (sync PostgreSQL URL)."
    )


def _get_session() -> Session:
    engine = create_engine(_SYNC_DB_URL)
    return Session(engine)


async def similarity_retriever(state: AgentBuilderState) -> dict:
    """
    Node 2: Search MCPs and Skills by similarity.
    Returns top 10 MCPs and top 5 Skills.
    """
    sub_queries = state["sub_queries"]
    max_mcps = state.get("max_mcps", 10)
    logger.info(f"🔎 Node 2: Searching with {len(sub_queries)} queries...")

    retrieved_mcps = []
    retrieved_skills = []

    try:
        # Generate embedding for the combined query
        combined_query = " ".join(sub_queries)
        query_embedding = await embedding_generator.generate(combined_query)

        session = _get_session()
        try:
            # --- Search MCPs ---
            # Check if MCPs have embeddings, if not do text-based search
            mcp_count = session.execute(
                text("SELECT COUNT(*) FROM mcps WHERE embedding IS NOT NULL AND is_active = true")
            ).scalar()

            if mcp_count and mcp_count > 0:
                # Vector similarity search
                mcp_results = session.execute(
                    text("""
                        SELECT id, mcp_name, docker_image, description, tools_provided,
                               default_ports, category, run_config,
                               1 - (embedding <=> CAST(:query_vec AS vector)) as similarity
                        FROM mcps
                        WHERE is_active = true AND embedding IS NOT NULL
                        ORDER BY embedding <=> CAST(:query_vec AS vector)
                        LIMIT :limit
                    """),
                    {"query_vec": str(query_embedding), "limit": max_mcps},
                ).fetchall()

                for row in mcp_results:
                    retrieved_mcps.append({
                        "id": row[0],
                        "mcp_name": row[1],
                        "docker_image": row[2],
                        "description": row[3],
                        "tools_provided": row[4],
                        "default_ports": row[5],
                        "category": row[6],
                        "run_config": row[7],
                        "similarity": float(row[8]) if row[8] else 0.0,
                    })
            else:
                # Fallback: text-based search using ILIKE
                logger.warning("No MCP embeddings found, using text search fallback")
                for sq in sub_queries[:3]:
                    mcp_results = session.execute(
                        text("""
                            SELECT id, mcp_name, docker_image, description, tools_provided,
                                   default_ports, category, run_config
                            FROM mcps
                            WHERE is_active = true AND (
                                description ILIKE :pattern OR mcp_name ILIKE :pattern
                            )
                            LIMIT :limit
                        """),
                        {"pattern": f"%{sq}%", "limit": max_mcps},
                    ).fetchall()

                    for row in mcp_results:
                        if not any(m["id"] == row[0] for m in retrieved_mcps):
                            retrieved_mcps.append({
                                "id": row[0],
                                "mcp_name": row[1],
                                "docker_image": row[2],
                                "description": row[3],
                                "tools_provided": row[4],
                                "default_ports": row[5],
                                "category": row[6],
                                "run_config": row[7],
                                "similarity": 0.5,
                            })

            # --- Search Skills ---
            skill_count = session.execute(
                text("SELECT COUNT(*) FROM skills WHERE embedding IS NOT NULL AND status = 'active'")
            ).scalar()

            if skill_count and skill_count > 0:
                skill_results = session.execute(
                    text("""
                        SELECT id, skill_id, skill_name, description, status, version, skill_data,
                               1 - (embedding <=> CAST(:query_vec AS vector)) as similarity,
                               system_prompt, category, source
                        FROM skills
                        WHERE status = 'active' AND embedding IS NOT NULL
                        ORDER BY embedding <=> CAST(:query_vec AS vector)
                        LIMIT 8
                    """),
                    {"query_vec": str(query_embedding)},
                ).fetchall()

                for row in skill_results:
                    retrieved_skills.append({
                        "id": str(row[0]),
                        "skill_id": row[1],
                        "skill_name": row[2],
                        "description": row[3],
                        "status": row[4],
                        "version": row[5],
                        "skill_data": row[6],
                        "similarity": float(row[7]) if row[7] else 0.0,
                        "system_prompt": row[8] or "",
                        "category": row[9] or "",
                        "source": row[10] or "",
                    })
            else:
                # Fallback text search for skills
                for sq in sub_queries[:3]:
                    skill_results = session.execute(
                        text("""
                            SELECT id, skill_id, skill_name, description, status, version, skill_data
                            FROM skills
                            WHERE status = 'active' AND (
                                description ILIKE :pattern OR skill_id ILIKE :pattern
                            )
                            LIMIT 5
                        """),
                        {"pattern": f"%{sq}%"},
                    ).fetchall()

                    for row in skill_results:
                        sid = str(row[0])
                        if not any(s["id"] == sid for s in retrieved_skills):
                            retrieved_skills.append({
                                "id": sid,
                                "skill_id": row[1],
                                "skill_name": row[2],
                                "description": row[3],
                                "status": row[4],
                                "version": row[5],
                                "skill_data": row[6],
                                "similarity": 0.5,
                                "system_prompt": "",
                                "category": "",
                                "source": "",
                            })

        finally:
            session.close()

        logger.info(f"  Found {len(retrieved_mcps)} MCPs, {len(retrieved_skills)} Skills")
        return {
            "retrieved_mcps": retrieved_mcps,
            "retrieved_skills": retrieved_skills,
        }

    except Exception as e:
        logger.error(f"Similarity retriever failed: {e}")
        return {
            "retrieved_mcps": [],
            "retrieved_skills": [],
            "errors": state.get("errors", []) + [f"Similarity retriever: {str(e)}"],
        }
