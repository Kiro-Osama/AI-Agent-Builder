"""Initial schema - MCPs, Skills, BuildHistory (768-dim vectors)

Revision ID: 001
Revises: None
Create Date: 2026-03-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # --- MCPs Table (Static) ---
    op.create_table(
        "mcps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mcp_name", sa.String(100), unique=True, nullable=False),
        sa.Column("docker_image", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tools_provided", JSONB, server_default="[]"),
        sa.Column("default_ports", JSONB, server_default="[]"),
        sa.Column("category", sa.String(50)),
        sa.Column("run_config", JSONB, server_default="{}"),
        sa.Column("embedding", Vector(768)),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Skills Table (Dynamic) ---
    op.create_table(
        "skills",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("skill_id", sa.String(255), unique=True, nullable=False),
        sa.Column("skill_name", sa.String(200)),
        sa.Column("description", sa.Text()),
        sa.Column("embedding", Vector(768)),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("version", sa.String(20), server_default="v1.0"),
        sa.Column("source_folder_path", sa.String(255)),
        sa.Column("skill_data", JSONB, server_default="{}"),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("max_retries", sa.Integer(), server_default="3"),
        sa.Column("error_log", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Build History Table ---
    op.create_table(
        "build_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_id", sa.String(255), unique=True, nullable=False),
        sa.Column("user_query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), server_default="queued"),
        sa.Column("current_node", sa.String(50)),
        sa.Column("result_template", JSONB),
        sa.Column("selected_mcps", JSONB, server_default="[]"),
        sa.Column("selected_skills", JSONB, server_default="[]"),
        sa.Column("processing_log", JSONB, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Indexes ---
    op.create_index("idx_mcps_category", "mcps", ["category"])
    op.create_index("idx_skills_status", "skills", ["status"])
    op.create_index("idx_build_history_status", "build_history", ["status"])
    op.create_index("idx_build_history_task_id", "build_history", ["task_id"])


def downgrade() -> None:
    op.drop_table("build_history")
    op.drop_table("skills")
    op.drop_table("mcps")
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
