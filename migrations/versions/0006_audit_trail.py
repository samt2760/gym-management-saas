"""Add a durable tenant-scoped audit trail.

Revision ID: 0006_audit_trail
Revises: 0005_payment_renewal_integrity
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_audit_trail"
down_revision = "0005_payment_renewal_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gym_id"], ["gyms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_gym_id", "audit_logs", ["gym_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index(
        "ix_audit_logs_gym_created_at", "audit_logs", ["gym_id", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_actor_created_at",
        "audit_logs",
        ["actor_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_gym_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_gym_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_id", table_name="audit_logs")
    op.drop_table("audit_logs")
