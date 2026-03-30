# ============================================
# FastAPI Backend API
# ============================================
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements and install
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copy application code (API + Core only, no worker needed)
COPY api/ /app/api/
COPY core/ /app/core/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini
COPY db/seeds/ /app/db/seeds/

# Create skills directory
RUN mkdir -p /app/skills

# Make entrypoint executable
RUN chmod +x /app/api/entrypoint.sh

EXPOSE 8000

CMD ["/app/api/entrypoint.sh"]
