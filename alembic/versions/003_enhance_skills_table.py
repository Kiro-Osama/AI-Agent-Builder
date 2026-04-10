"""Add category, source, system_prompt columns to skills table

Revision ID: 003
Revises: 002
Create Date: 2026-04-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("category", sa.String(50), nullable=True))
    op.add_column("skills", sa.Column("source", sa.String(50), nullable=True))
    op.add_column("skills", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.create_index("idx_skills_category", "skills", ["category"])
    op.create_index("idx_skills_source", "skills", ["source"])


def downgrade() -> None:
    op.drop_index("idx_skills_source", table_name="skills")
    op.drop_index("idx_skills_category", table_name="skills")
    op.drop_column("skills", "system_prompt")
    op.drop_column("skills", "source")
    op.drop_column("skills", "category")
