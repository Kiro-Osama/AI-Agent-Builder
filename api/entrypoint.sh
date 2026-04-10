#!/bin/bash
# ============================================
# API Entrypoint Script
# 1. Alembic migrations (schema + seed data)
# 2. Auto-generate embeddings (Gemini API)
# 3. Start FastAPI
# ============================================
set -e

echo "🗄️ Running Alembic migrations..."
cd /app
alembic upgrade head

echo "🔢 Generating embeddings for MCPs..."
python /app/api/auto_embed.py

echo "🚀 Starting FastAPI..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
