"""
Admin Router — MCP Management
===============================
CRUD endpoints for managing MCPs in the catalog.
"""
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_db
from core.models import MCP

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


class MCPCreate(BaseModel):
    mcp_name: str = Field(..., min_length=2, max_length=100)
    docker_image: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=5)
    tools_provided: list[dict] = Field(default_factory=list)
    category: str | None = None
    run_config: dict = Field(default_factory=dict)
    requires_user_config: bool = False
    config_schema: list[dict] = Field(default_factory=list)


class MCPUpdate(BaseModel):
    mcp_name: str | None = None
    docker_image: str | None = None
    description: str | None = None
    tools_provided: list[dict] | None = None
    category: str | None = None
    run_config: dict | None = None
    requires_user_config: bool | None = None
    config_schema: list[dict] | None = None
    is_active: bool | None = None


@router.get("/mcps")
async def list_all_mcps(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List all MCPs including inactive ones."""
    query = select(MCP).order_by(MCP.category, MCP.mcp_name)
    if not include_inactive:
        query = query.where(MCP.is_active == True)

    result = await db.execute(query)
    mcps = result.scalars().all()

    return {
        "mcps": [m.to_dict() for m in mcps],
        "total": len(mcps),
    }


@router.post("/mcps", status_code=201)
async def create_mcp(
    body: MCPCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new MCP entry."""
    exists = await db.execute(select(MCP).where(MCP.mcp_name == body.mcp_name))
    if exists.scalar_one_or_none():
        raise HTTPException(409, f"MCP '{body.mcp_name}' already exists")

    mcp = MCP(
        mcp_name=body.mcp_name,
        docker_image=body.docker_image,
        description=body.description,
        tools_provided=body.tools_provided,
        category=body.category,
        run_config=body.run_config,
        requires_user_config=body.requires_user_config,
        config_schema=body.config_schema,
    )
    db.add(mcp)
    await db.commit()
    await db.refresh(mcp)

    background_tasks.add_task(_generate_embedding_for_mcp, mcp.id)

    return mcp.to_dict()


@router.put("/mcps/{mcp_id}")
async def update_mcp(
    mcp_id: int,
    body: MCPUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing MCP."""
    result = await db.execute(select(MCP).where(MCP.id == mcp_id))
    mcp = result.scalar_one_or_none()
    if not mcp:
        raise HTTPException(404, "MCP not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(mcp, key, value)

    await db.commit()
    await db.refresh(mcp)
    return mcp.to_dict()


@router.delete("/mcps/{mcp_id}")
async def delete_mcp(
    mcp_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate) an MCP."""
    result = await db.execute(select(MCP).where(MCP.id == mcp_id))
    mcp = result.scalar_one_or_none()
    if not mcp:
        raise HTTPException(404, "MCP not found")

    mcp.is_active = False
    await db.commit()
    return {"status": "deactivated", "mcp_name": mcp.mcp_name}


@router.post("/mcps/{mcp_id}/test")
async def test_mcp(
    mcp_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Test-start an MCP container, list its tools, then stop it."""
    result = await db.execute(select(MCP).where(MCP.id == mcp_id))
    mcp = result.scalar_one_or_none()
    if not mcp:
        raise HTTPException(404, "MCP not found")

    if mcp.requires_user_config:
        env = (mcp.run_config or {}).get("environment", {})
        missing = [k for k, v in env.items() if v == "REQUIRED"]
        if missing:
            return {
                "status": "skipped",
                "reason": f"MCP requires user config: {', '.join(missing)}",
                "mcp_name": mcp.mcp_name,
            }

    from core.mcp_client import MCPContainerSession
    import os

    container = MCPContainerSession()
    try:
        await container.start(
            docker_image=mcp.docker_image,
            run_config=mcp.run_config or {},
            workspace_path=os.getenv("WORKSPACE_PATH", "/workspace"),
            mcp_name=mcp.mcp_name,
        )
        await container.initialize()
        tools = await container.list_tools()
        tool_names = [t["name"] for t in tools]

        return {
            "status": "ok",
            "mcp_name": mcp.mcp_name,
            "docker_image": mcp.docker_image,
            "tools_discovered": tool_names,
            "tools_count": len(tools),
        }
    except Exception as e:
        return {
            "status": "error",
            "mcp_name": mcp.mcp_name,
            "error": str(e),
        }
    finally:
        await container.stop()


def _generate_embedding_for_mcp(mcp_id: int):
    """Background task to generate embedding for a single MCP."""
    try:
        from core.embeddings_service import EmbeddingsService
        svc = EmbeddingsService()
        svc.embed_single_mcp(mcp_id)
    except Exception as e:
        logger.warning(f"Background embedding for MCP {mcp_id} failed: {e}")
