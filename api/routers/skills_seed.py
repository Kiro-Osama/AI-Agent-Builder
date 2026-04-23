"""
Skills Seed Router
===================
GET  /api/v1/skills/scan  — discover SKILL.md files on disk, report DB status
POST /api/v1/skills/seed  — upsert discovered skills into the database
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import async_session_factory, get_db
from core.models import Skill

logger = logging.getLogger(__name__)
router = APIRouter()

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills" / "skills"

CATEGORY_MAP: dict[str, str] = {
    "pdf": "documents",
    "docx": "documents",
    "pptx": "documents",
    "xlsx": "documents",
    "doc-coauthoring": "documents",
    "algorithmic-art": "design",
    "brand-guidelines": "design",
    "canvas-design": "design",
    "frontend-design": "design",
    "theme-factory": "design",
    "web-artifacts-builder": "design",
    "slack-gif-creator": "design",
    "claude-api": "development",
    "mcp-builder": "development",
    "webapp-testing": "development",
    "skill-creator": "development",
    "internal-comms": "communication",
}


def _catalog_skill_files(skill_dir: Path) -> list[dict[str, Any]]:
    """
    List all files in a skill directory for DeepAgent progressive disclosure.
    The agent uses read_file/execute tools to access these on-demand.
    """
    files: list[dict[str, Any]] = []
    for f in sorted(skill_dir.rglob("*")):
        if f.is_file() and f.name not in ("LICENSE.txt", ".gitkeep"):
            files.append({
                "relative_path": str(f.relative_to(skill_dir)),
                "size_bytes": f.stat().st_size,
                "type": f.suffix.lstrip(".") or "unknown",
            })
    return files


def _parse_skill_md(path: Path) -> dict[str, Any] | None:
    """Parse a SKILL.md file, extracting YAML frontmatter and markdown body."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Could not read %s", path)
        return None

    fm: dict[str, str] = {}
    body = raw

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", raw, re.DOTALL)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fm[key.strip()] = val.strip().strip('"').strip("'")
        body = match.group(2).strip()

    name = fm.get("name", "")
    if not name:
        return None

    # Catalog all files in the skill folder for DeepAgent discovery
    file_catalog = _catalog_skill_files(path.parent)

    return {
        "skill_id": name,
        "skill_name": name.replace("-", " ").title(),
        "description": fm.get("description", ""),
        "license": fm.get("license", ""),
        "system_prompt": body,
        "folder_path": str(path.parent),
        "file_catalog": file_catalog,
    }


def _scan_disk() -> list[dict[str, Any]]:
    """Walk SKILLS_ROOT and return parsed skill metadata."""
    results: list[dict[str, Any]] = []
    if not SKILLS_ROOT.is_dir():
        return results
    for child in sorted(SKILLS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        md_path = child / "SKILL.md"
        if md_path.is_file():
            parsed = _parse_skill_md(md_path)
            if parsed:
                results.append(parsed)
    return results



class SeedRequest(BaseModel):
    skill_ids: list[str] | None = None


async def _run_skill_embeddings_after_seed() -> None:
    """Run in background so POST /skills/seed returns immediately (avoids UI hang)."""
    try:
        from core.embeddings_service import run_catalog_embeddings

        async with async_session_factory() as session:
            await run_catalog_embeddings(
                session, only_missing=True, include_mcps=False, include_skills=True
            )
    except Exception:
        logger.exception("Background skill embedding after seed failed")


@router.get("/skills/scan")
async def scan_skills(db: AsyncSession = Depends(get_db)):
    """Discover SKILL.md files on disk and report which ones exist in the DB."""
    on_disk = _scan_disk()
    if not on_disk:
        return {"skills": [], "total": 0, "skills_root": str(SKILLS_ROOT)}

    ids = [s["skill_id"] for s in on_disk]
    result = await db.execute(select(Skill).where(Skill.skill_id.in_(ids)))
    existing = {s.skill_id: s for s in result.scalars().all()}

    items = []
    for s in on_disk:
        sid = s["skill_id"]
        in_db = sid in existing
        items.append({
            **s,
            "in_db": in_db,
            "category": CATEGORY_MAP.get(sid, "general"),
            "has_embedding": existing[sid].embedding is not None if in_db else False,
        })

    return {"skills": items, "total": len(items), "skills_root": str(SKILLS_ROOT)}


@router.post("/skills/seed")
async def seed_skills(
    background_tasks: BackgroundTasks,
    body: SeedRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Upsert skills from disk; embeddings run in the background (non-blocking)."""
    on_disk = _scan_disk()
    if not on_disk:
        raise HTTPException(status_code=404, detail="No SKILL.md files found on disk")

    requested_ids = (body.skill_ids if body and body.skill_ids else None)
    if requested_ids:
        on_disk = [s for s in on_disk if s["skill_id"] in requested_ids]
        if not on_disk:
            raise HTTPException(status_code=404, detail="None of the requested skill_ids were found on disk")

    ids = [s["skill_id"] for s in on_disk]
    result = await db.execute(select(Skill).where(Skill.skill_id.in_(ids)))
    existing = {s.skill_id: s for s in result.scalars().all()}

    inserted = 0
    updated = 0

    for s in on_disk:
        sid = s["skill_id"]
        category = CATEGORY_MAP.get(sid, "general")
        skill_data = {}
        if s.get("license"):
            skill_data["license"] = s["license"]
        if s.get("file_catalog"):
            skill_data["file_catalog"] = s["file_catalog"]

        if sid in existing:
            row = existing[sid]
            row.skill_name = s["skill_name"]
            row.description = s["description"]
            row.system_prompt = s["system_prompt"]
            row.source_folder_path = s["folder_path"]
            row.category = category
            row.source = "seeded"
            row.status = "active"
            row.skill_data = {**(row.skill_data or {}), **skill_data}
            updated += 1
        else:
            row = Skill(
                skill_id=sid,
                skill_name=s["skill_name"],
                description=s["description"],
                system_prompt=s["system_prompt"],
                source_folder_path=s["folder_path"],
                category=category,
                source="seeded",
                status="active",
                skill_data=skill_data,
            )
            db.add(row)
            inserted += 1

    await db.commit()

    background_tasks.add_task(_run_skill_embeddings_after_seed)

    return {
        "inserted": inserted,
        "updated": updated,
        "total_processed": inserted + updated,
        "embeddings": {
            "status": "queued",
            "message": "Embedding generation started in the background. Use 'Generate embeddings' or refresh status in ~1 minute.",
        },
    }
