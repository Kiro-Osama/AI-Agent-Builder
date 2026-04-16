"""
Resolve MCP user-config requirements for chat UIs.

Templates stored in build_history often omit `requires_user_config` / `config_schema`
because pipeline merge only injects docker/run_config/tools — so we join `mcps` by name.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import MCP


async def mcp_config_required_for_modal(
    db: AsyncSession,
    selected_mcps: list[dict],
) -> list[dict]:
    """
    Return entries like [{"mcp_name": "...", "config_schema": [...]}, ...]
    for MCPs that need user-supplied keys (deduped by mcp_name).
    """
    names = list({m.get("mcp_name") for m in selected_mcps if m.get("mcp_name")})
    if not names:
        return []

    result = await db.execute(select(MCP).where(MCP.mcp_name.in_(names)))
    by_name = {row.mcp_name: row for row in result.scalars().all()}

    out: list[dict] = []
    seen: set[str] = set()
    for mcp in selected_mcps:
        name = mcp.get("mcp_name")
        if not name or name in seen:
            continue
        row = by_name.get(name)
        req = mcp.get("requires_user_config")
        if req is None and row is not None:
            req = bool(row.requires_user_config)
        schema = mcp.get("config_schema")
        if (not schema) and row is not None:
            schema = row.config_schema or []
        if not req:
            continue
        seen.add(name)
        sch = list(schema) if isinstance(schema, list) else []
        out.append({"mcp_name": name, "config_schema": sch})
    return out
