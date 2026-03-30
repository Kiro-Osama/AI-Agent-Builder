#!/bin/bash
# ============================================
# API Entrypoint Script
# 1. Wait for DB
# 2. Alembic migrations (stamps if tables exist from init SQL)
# 3. Auto-generate embeddings (Gemini API)
# 4. Start FastAPI
# ============================================
set -e

echo "🗄️ Running Alembic migrations..."
cd /app

# Stamp existing schema if tables already created by postgres init
alembic upgrade head 2>/dev/null || {
    echo "⚠️ Alembic upgrade failed (tables may already exist from init SQL), stamping head..."
    alembic stamp head 2>/dev/null || true
}

# Seeds are now handled by DB container's docker-entrypoint-initdb.d
# Just generate embeddings for any MCPs that need them
echo "🔢 Generating embeddings for MCPs..."
python /app/api/auto_embed.py

echo "🚀 Starting FastAPI..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
