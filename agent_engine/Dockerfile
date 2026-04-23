# ============================================
# Deep Agent Engine
# ============================================
# Dedicated container for running DeepAgent instances.
# Each agent chat session runs inside this isolated environment.
# Skills are mounted as read-only volumes.
# Workspace is a sandboxed writable volume.
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (needed for MCP container stdio transport)
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements (shared base) and install
COPY requirements/ /app/requirements/
COPY agent_engine/requirements.txt /app/agent_engine/requirements.txt
RUN pip install --no-cache-dir \
    -r /app/requirements/base.txt \
    -r /app/agent_engine/requirements.txt

# Copy core modules (deep_agent_runtime, mcp_adapter, models, db, etc.)
COPY core/ /app/core/

# Copy agent engine server
COPY agent_engine/ /app/agent_engine/

# Create directories for runtime
RUN mkdir -p /app/skills /app/workspace

# Skills directory (mounted read-only at runtime via docker-compose)
ENV SKILLS_DIR=/app/skills/skills
# Sandboxed workspace for agent file operations
ENV WORKSPACE_DIR=/app/workspace

EXPOSE 8001

CMD ["python", "-m", "agent_engine.server"]
