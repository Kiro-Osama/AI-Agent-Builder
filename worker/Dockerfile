# ============================================
# Celery Worker
# ============================================
FROM python:3.11-slim

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (needed to start MCP containers via subprocess)
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements (shared base + worker-specific) and install
COPY requirements/ /app/requirements/
COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/worker/requirements.txt

# Copy application code
COPY worker/ /app/worker/
COPY core/ /app/core/
COPY orchestrator/ /app/orchestrator/

# Create skills directory
RUN mkdir -p /app/skills

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "--concurrency=4"]
