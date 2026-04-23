"""
Celery Application Configuration
==================================
Redis broker, result backend, and task serialization.
"""
import os

from dotenv import load_dotenv
from celery import Celery

load_dotenv()

from core.langsmith_env import apply_langsmith_env

apply_langsmith_env()

# -----------------------------------------------
# Celery App
# -----------------------------------------------
app = Celery("agent_builder")

# Configuration
app.conf.update(
    # Broker (Redis)
    broker_url=os.getenv("REDIS_URL", "redis://redis:6379/0").strip(),
    result_backend=os.getenv("REDIS_URL", "redis://redis:6379/0").strip(),

    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task behavior
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Result expiration (24 hours)
    result_expires=86400,

    # Task routes
    task_routes={
        "worker.tasks.build_agent.*": {"queue": "build"},
        "worker.tasks.build_workflow.*": {"queue": "build"},
        "worker.tasks.sandbox_validator.*": {"queue": "sandbox"},
    },

    # Default queue
    task_default_queue="build",
)

# Explicitly import task modules so Celery registers them
app.conf.imports = [
    "worker.tasks.build_agent",
    "worker.tasks.build_workflow",
    "worker.tasks.sandbox_validator",
]
