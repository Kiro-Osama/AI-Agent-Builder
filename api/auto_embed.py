"""
Auto-Embed Script
==================
Generates real embeddings for all MCPs that have NULL embeddings.
Uses Google Gemini text-embedding-004 API (FREE).
Runs at startup after migrations and seeds.
"""
import sys
import os
sys.path.insert(0, "/app")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import httpx

SYNC_DB_URL = os.getenv(
    "ALEMBIC_DATABASE_URL",
    "postgresql://agentbuilder:secure_password_change_me@db:5432/agentbuilder_db",
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-embedding-001"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def get_embedding(text_input: str) -> list[float]:
    """Get embedding from Google Gemini API."""
    url = f"{GEMINI_BASE_URL}/models/{GEMINI_MODEL}:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": f"models/{GEMINI_MODEL}",
        "content": {"parts": [{"text": text_input}]},
        "outputDimensionality": 768
    }
    response = httpx.post(url, json=payload, timeout=30.0)
    response.raise_for_status()
    return response.json()["embedding"]["values"]


def main():
    if not GEMINI_API_KEY:
        print("⚠️ Auto-Embed: GEMINI_API_KEY not set, skipping")
        return

    engine = create_engine(SYNC_DB_URL)
    session = Session(engine)

    try:
        # Get ALL MCPs - re-embed everything since seeds may have been updated
        rows = session.execute(
            text("SELECT id, mcp_name, description FROM mcps WHERE is_active = true")
        ).fetchall()

        if not rows:
            print("🔢 Auto-Embed: No MCPs found in database")
            return

        print(f"🔢 Auto-Embed: Generating embeddings for {len(rows)} MCPs via Gemini API...")

        for row_id, name, description in rows:
            embedding = get_embedding(description)
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            session.execute(
                text("UPDATE mcps SET embedding = CAST(:vec AS vector) WHERE id = :id"),
                {"vec": vec_str, "id": row_id},
            )
            print(f"   ✅ {name} ({len(embedding)} dims)")

        session.commit()
        print(f"🔢 Auto-Embed: Done! {len(rows)} MCPs embedded.")

    except Exception as e:
        print(f"❌ Auto-Embed error: {e}")
        session.rollback()
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
