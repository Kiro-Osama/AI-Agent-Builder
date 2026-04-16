"""Create workflows and workflow_executions tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-10
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS workflows (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(200),
            description TEXT,
            user_query TEXT NOT NULL,
            topology VARCHAR(50) NOT NULL DEFAULT 'sequential',
            workflow_config JSONB DEFAULT '{}'::jsonb,
            agents JSONB DEFAULT '[]'::jsonb,
            shared_state_schema JSONB DEFAULT '{}'::jsonb,
            status VARCHAR(50) DEFAULT 'planning',
            build_task_ids JSONB DEFAULT '[]'::jsonb,
            error_log TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    op.execute(text("""
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id VARCHAR(255) NOT NULL REFERENCES workflows(workflow_id),
            conversation_id VARCHAR(255) NOT NULL,
            shared_state JSONB DEFAULT '{}'::jsonb,
            execution_log JSONB DEFAULT '[]'::jsonb,
            current_agent VARCHAR(100),
            status VARCHAR(50) DEFAULT 'active',
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    op.execute(text("CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_wf_exec_workflow_id ON workflow_executions(workflow_id)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_wf_exec_conv_id ON workflow_executions(conversation_id)"))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS workflow_executions"))
    op.execute(text("DROP TABLE IF EXISTS workflows"))
