"""
API — FastAPI application serving the Agent Builder REST interface.

Routers:
    build           POST /api/v1/build — submit agent build request
    status          GET  /api/v1/status/{task_id} — poll pipeline progress
    chat            POST /api/v1/chat/{task_id} — chat with built agent
    templates       GET  /api/v1/mcps, /api/v1/skills — list catalog
    embeddings      POST /api/v1/embeddings/run — generate embeddings
    skills_seed     POST /api/v1/skills/seed — seed skills from disk
"""
