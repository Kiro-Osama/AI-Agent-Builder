# ============================================
# Celery Worker
# ============================================
FROM python:3.11-slim

# Install system dependencies (Docker CLI for container management)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements and install
COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/worker/requirements.txt

# Copy application code
COPY worker/ /app/worker/
COPY core/ /app/core/
COPY orchestrator/ /app/orchestrator/

# Create skills directory
RUN mkdir -p /app/skills

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
