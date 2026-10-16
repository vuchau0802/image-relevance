"""Add durable attributed AI call records.

Revision ID: e5a0c4d8b912
Revises: d70f04f97eaa
"""

from alembic import op
import sqlalchemy as sa

revision = "e5a0c4d8b912"
down_revision = "d70f04f97eaa"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_calls",
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("call_id", sa.String(36), nullable=False),
        sa.Column("image_id", sa.String(100), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("job_item_id", sa.String(36), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="started"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_basis", sa.String(200), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "call_id"),
        sa.CheckConstraint("status IN ('started', 'completed', 'needs_review', 'failed', 'interrupted')", name="ck_ai_calls_status"),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_calls_input_tokens"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_calls_output_tokens"),
        sa.CheckConstraint("estimated_cost_usd >= 0", name="ck_ai_calls_cost"),
    )
    op.create_index("ix_ai_calls_tenant_created", "ai_calls", ["tenant_id", "created_at"])


def downgrade():
    op.drop_index("ix_ai_calls_tenant_created", table_name="ai_calls")
    op.drop_table("ai_calls")
