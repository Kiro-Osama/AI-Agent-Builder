"""Per-workflow limits for sub-agent builds (MCPs + skills catalog retrieval).

Revision ID: 006
Revises: 005
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("""
        ALTER TABLE workflows
        ADD COLUMN IF NOT EXISTS sub_build_max_mcps INTEGER DEFAULT 3
    """))
    op.execute(text("""
        ALTER TABLE workflows
        ADD COLUMN IF NOT EXISTS sub_build_max_skills INTEGER DEFAULT 8
    """))


def downgrade() -> None:
    op.execute(text("ALTER TABLE workflows DROP COLUMN IF EXISTS sub_build_max_skills"))
    op.execute(text("ALTER TABLE workflows DROP COLUMN IF EXISTS sub_build_max_mcps"))
