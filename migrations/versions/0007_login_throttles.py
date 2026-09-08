"""Add database-backed login throttling state.

Revision ID: 0007_login_throttles
Revises: 0006_audit_trail
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_login_throttles"
down_revision = "0006_audit_trail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_throttles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key_hash", name="uq_login_throttles_key_hash"),
    )
    op.create_index("ix_login_throttles_id", "login_throttles", ["id"])
    op.create_index(
        "ix_login_throttles_last_attempt_at", "login_throttles", ["last_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_login_throttles_last_attempt_at", table_name="login_throttles")
    op.drop_index("ix_login_throttles_id", table_name="login_throttles")
    op.drop_table("login_throttles")
