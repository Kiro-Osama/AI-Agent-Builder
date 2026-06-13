# Agent Builder System

Dynamic AI Agent Builder with LangGraph orchestration, MCP tools, and skill creation.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frontend   │────▶│   FastAPI    │────▶│   Celery    │
│  (Nginx:3000)│◀────│  (API:8000)  │◀────│  (Worker)   │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                     │
                    ┌──────┴───────┐      ┌──────┴──────┐
                    │  PostgreSQL  │      │ LangGraph   │
                    │  + pgvector  │      │  Pipeline   │
                    └──────────────┘      └─────────────┘
```

### Pipeline (9 nodes)

1. **Query Analyzer** — Breaks user task into search queries
2. **Similarity Retriever** — Finds relevant MCPs and skills via pgvector
3. **Needs Assessment** — Decides if existing tools are sufficient or new skills needed
4. **Skill Creator** — Generates new skills dynamically when gaps found
5. **Sandbox Validator** — Tests new skills in isolated Docker containers
6. **AI Final Filter** — Selects minimal set of tools for the task
7. **Docker MCP Runner** — Prepares MCP container configs
8. **Template Builder** — Assembles the final agent configuration
9. **Final Output** — Validates and delivers the template

### Services

| Service    | Port | Description                        |
|------------|------|------------------------------------|
| Frontend   | 3000 | Dashboard UI (Nginx)               |
| API        | 8000 | FastAPI gateway                    |
| PostgreSQL | 5432 | Database with pgvector extension   |
| Redis      | 6379 | Celery broker + result backend     |
| Adminer    | 8080 | DB admin (dev profile only)        |

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your API keys

# 2. Start all services
make up

# 3. Run database migrations
make migrate

# 4. Open the dashboard
# http://localhost:3000
```

## Project Structure

```
├── api/                    # FastAPI application
│   ├── routers/            # API endpoints (build, chat, status, etc.)
│   ├── schemas/            # Pydantic request/response models
│   ├── services/           # Business logic (task dispatcher)
│   ├── config.py           # Pydantic settings from env
│   └── main.py             # App entry point + lifespan
├── core/                   # Shared libraries (used by API + Worker)
│   ├── agent_loop.py       # ReAct agent execution (LLM ↔ MCP tools)
│   ├── agent_session.py    # MCP container session management
│   ├── db.py               # Async SQLAlchemy engine
│   ├── docker_manager.py   # Docker SDK wrapper for sandboxes
│   ├── embeddings.py       # Gemini embedding client
│   ├── embeddings_service.py # Batch embedding generation
│   ├── mcp_client.py       # JSON-RPC over Docker stdio (MCP protocol)
│   ├── models.py           # SQLAlchemy ORM models
│   └── openrouter.py       # Multi-model LLM client with fallback
├── orchestrator/           # LangGraph pipeline
│   ├── graph.py            # Graph wiring (9 nodes)
│   ├── state.py            # TypedDict state definition
│   └── nodes/              # Individual pipeline nodes
├── worker/                 # Celery async task processor
│   ├── celery_app.py       # Celery configuration
│   └── tasks/              # Task definitions
├── frontend/               # Static dashboard (HTML/CSS/JS)
├── alembic/                # Database migrations
├── db/                     # PostgreSQL + pgvector Dockerfile
├── skills/                 # Skill definitions and templates
├── requirements/           # Shared Python dependencies
│   ├── base.txt            # Common packages
│   ├── api.txt             # API-specific packages
│   └── worker.txt          # Worker-specific packages
├── tests/                  # Test suite
├── docker-compose.yml      # Service orchestration
├── Makefile                # Common commands
└── .env.example            # Environment template
```

## Make Commands

```bash
make up          # Start all services
make down        # Stop all services
make build       # Rebuild and start
make logs        # Follow all logs
make logs-api    # Follow API logs
make logs-worker # Follow worker logs
make migrate     # Run Alembic migrations
make db-shell    # Open psql shell
make test        # Run tests
make dev         # Start with dev profile (includes Adminer)
make clean       # Remove everything (volumes included)
```

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable               | Required | Description                          |
|------------------------|----------|--------------------------------------|
| `OPENROUTER_API_KEY`   | Yes      | Primary OpenRouter API key           |
| `GEMINI_API_KEY`       | Yes      | Google Gemini API key for embeddings |
| `POSTGRES_PASSWORD`    | Yes      | Database password                    |
| `DATABASE_URL`         | Yes      | Async DB connection string           |
| `ALEMBIC_DATABASE_URL` | Yes      | Sync DB connection string            |
| `REDIS_URL`            | Yes      | Redis connection string              |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Celery
- **Pipeline**: LangGraph (StateGraph with conditional edges)
- **Database**: PostgreSQL 16 + pgvector
- **LLM**: OpenRouter (multi-model gateway with fallback chain)
- **Embeddings**: Google Gemini
- **MCP Protocol**: JSON-RPC 2.0 over Docker stdio
- **Frontend**: Vanilla HTML/CSS/JS, Nginx
- **Infrastructure**: Docker Compose, Redis
