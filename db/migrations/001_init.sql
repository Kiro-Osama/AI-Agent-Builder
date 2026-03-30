-- ============================================
-- Agent Builder System V5 - Database Init
-- Migration 001: Core Tables
-- ============================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------
-- MCPs Table (Static - pulled from Docker Hub)
-- These are NEVER created dynamically by the AI.
-- The system only SELECTS from this table.
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS mcps (
    id SERIAL PRIMARY KEY,                     -- Auto-increment ID
    mcp_name VARCHAR(100) UNIQUE NOT NULL,     -- e.g. "mcp-kali-linux"
    docker_image VARCHAR(255) NOT NULL,        -- e.g. "mcp/fetch:latest"
    description TEXT NOT NULL,                 -- Semantic description for search
    tools_provided JSONB DEFAULT '[]'::jsonb,  -- OpenRouter-format tool definitions
    default_ports JSONB DEFAULT '[]'::jsonb,   -- Default exposed ports
    category VARCHAR(50),                      -- e.g. "security", "files", "web"
    run_config JSONB DEFAULT '{}'::jsonb,      -- Docker run config:
    /*
      run_config JSON structure:
      {
        "command": ["/workspace"],           -- CMD arguments
        "volumes": {"/host/path": "/container/path"},
        "environment": {"KEY": "VALUE"},     -- env vars
        "stdin_open": true,                  -- -i flag (needed for stdio transport)
        "transport": "stdio" | "http",       -- how the MCP communicates
        "expose_ports": {"3000": "3000"},    -- port mapping (for http transport)
        "network_mode": "host",              -- optional network mode
        "extra_flags": []                    -- any additional docker flags
      }
    */
    embedding vector(768),                    -- Vector for semantic search
    is_active BOOLEAN DEFAULT true,            -- Soft-disable flag
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------
-- Skills Table (Dynamic - AI can create these)
-- The Builder Agent can INSERT new skills.
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id VARCHAR(255) UNIQUE NOT NULL,         -- e.g. "pdf-analyzer-skill"
    skill_name VARCHAR(200),                       -- Human-readable name
    description TEXT,                              -- Semantic description
    embedding vector(768),                        -- Vector for semantic search
    status VARCHAR(50) DEFAULT 'pending',          -- pending | testing | active | failed
    version VARCHAR(20) DEFAULT 'v1.0',            -- Version tracking
    source_folder_path VARCHAR(255),               -- Path to skill code
    skill_data JSONB DEFAULT '{}'::jsonb,          -- Full payload:
    /*
      skill_data JSON structure:
      {
        "system_prompt": "You are a PDF expert agent...",
        "tools_schema": [{"name": "extract_text", "description": "...", "parameters": {...}}],
        "execution_env": "python:3.9-slim",
        "env_requirements": ["OPENAI_API_KEY"],
        "assets": ["reference.md"],
        "code": "def main(): ..."
      }
    */
    retry_count INT DEFAULT 0,                     -- Number of build retries
    max_retries INT DEFAULT 3,                     -- Max allowed retries
    error_log TEXT,                                 -- Last error message
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------
-- Build History Table (Track all build requests)
-- -----------------------------------------------
CREATE TABLE IF NOT EXISTS build_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id VARCHAR(255) UNIQUE NOT NULL,           -- Celery task ID
    user_query TEXT NOT NULL,                        -- Original user request
    status VARCHAR(50) DEFAULT 'queued',            -- queued | processing | completed | failed
    current_node VARCHAR(50),                       -- Current LangGraph node
    result_template JSONB,                          -- Final output template
    selected_mcps JSONB DEFAULT '[]'::jsonb,        -- MCPs selected by pipeline
    selected_skills JSONB DEFAULT '[]'::jsonb,      -- Skills selected/created
    processing_log JSONB DEFAULT '[]'::jsonb,       -- Step-by-step logs
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------
-- Indexes for performance
-- -----------------------------------------------
CREATE INDEX IF NOT EXISTS idx_mcps_category ON mcps (category);
CREATE INDEX IF NOT EXISTS idx_skills_status ON skills (status);
CREATE INDEX IF NOT EXISTS idx_build_history_status ON build_history (status);
CREATE INDEX IF NOT EXISTS idx_build_history_task_id ON build_history (task_id);
