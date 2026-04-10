"""
Auto-Embed Script
==================
Generates real embeddings for MCPs (and skills with descriptions).
Uses Google Gemini embed API. Runs at API startup after migrations.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

from core.db import async_session_factory
from core.embeddings_service import run_catalog_embeddings


async def _async_main() -> None:
    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("⚠️ Auto-Embed: GEMINI_API_KEY not set, skipping")
        return

    async with async_session_factory() as db:
        try:
            result = await run_catalog_embeddings(
                db,
                only_missing=True,
                include_mcps=True,
                include_skills=True,
            )
            print(
                f"🔢 Auto-Embed: mcps={result['embedded_mcps']} skills={result['embedded_skills']} "
                f"errors={len(result['errors'])}"
            )
            if result["errors"]:
                for err in result["errors"]:
                    print(f"   ⚠️ {err}")
        except Exception as e:
            print(f"❌ Auto-Embed error: {e}")
            await db.rollback()
            raise


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
