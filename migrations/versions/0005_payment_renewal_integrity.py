"""Harden payment ledger state and renewal idempotency.

Revision ID: 0005_payment_renewal_integrity
Revises: 0004_align_authentication_token_columns
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_payment_renewal_integrity"
down_revision = "0004_align_authentication_token_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "payments",
        sa.Column("status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.execute(sa.text("UPDATE payments SET status = 'Completed' WHERE status IS NULL"))

    if bind.dialect.name == "postgresql":
        op.alter_column(
            "payments",
            "status",
            existing_type=sa.String(length=16),
            nullable=False,
            server_default="Completed",
        )
        op.create_check_constraint(
            "ck_payments_valid_status",
            "payments",
            "status IN ('Completed', 'Voided')",
        )
    else:
        with op.batch_alter_table("payments", recreate="always") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=sa.String(length=16),
                nullable=False,
                server_default="Completed",
            )
            batch_op.create_check_constraint(
                "ck_payments_valid_status",
                "status IN ('Completed', 'Voided')",
            )

    op.create_index(
        "uq_payments_gym_idempotency_key",
        "payments",
        ["gym_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("uq_payments_gym_idempotency_key", table_name="payments")
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_payments_valid_status", "payments", type_="check")
        op.drop_column("payments", "idempotency_key")
        op.drop_column("payments", "status")
    else:
        with op.batch_alter_table("payments", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_payments_valid_status", type_="check")
            batch_op.drop_column("idempotency_key")
            batch_op.drop_column("status")
