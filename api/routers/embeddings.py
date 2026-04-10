"""
Embedding catalog API — status and on-demand Gemini embedding runs.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.embeddings_service import get_embedding_catalog_status, run_catalog_embeddings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/embeddings/status")
async def embeddings_status(db: AsyncSession = Depends(get_db)):
    """Return embedding coverage for MCPs and skills (per-row flags)."""
    return await get_embedding_catalog_status(db)


@router.post("/embeddings/run")
async def embeddings_run(
    only_missing: bool = Query(True, description="If true, only rows with NULL embedding are updated."),
    include_mcps: bool = Query(True),
    include_skills: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate embeddings via Gemini for MCPs and/or skills.
    Requires GEMINI_API_KEY.
    """
    try:
        result = await run_catalog_embeddings(
            db,
            only_missing=only_missing,
            include_mcps=include_mcps,
            include_skills=include_skills,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Embedding run failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    summary = await get_embedding_catalog_status(db)
    return {
        **result,
        "status_after": summary,
    }
