"""
Alembic Environment Configuration
===================================
Supports both sync and async migration execution.
"""
import os
from logging.config import fileConfig

from sqlalchemy import pool, create_engine
from alembic import context

# Import models to register metadata
from core.db import Base
from core.models import MCP, Skill, BuildHistory  # noqa: F401

# Alembic Config object
config = context.config

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = Base.metadata

# Get DB URL from environment (no baked-in credentials)
DATABASE_URL = os.getenv("ALEMBIC_DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "ALEMBIC_DATABASE_URL is required for Alembic (e.g. postgresql://user:pass@host:5432/dbname)."
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without DB connection)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with DB connection)."""
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
