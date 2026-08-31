"""Harden the legacy SQLite schema without losing operational history.

Revision ID: 0001_database_hardening
Revises:
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_database_hardening"
down_revision = None
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def _create_current_schema() -> None:
    """Create the complete schema for a brand-new database."""

    op.create_table(
        "gyms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column(
            "registration_fee",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "monthly_fee",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "registration_fee >= 0",
            name="ck_gyms_registration_fee_nonnegative",
        ),
        sa.CheckConstraint(
            "monthly_fee >= 0",
            name="ck_gyms_monthly_fee_nonnegative",
        ),
    )

    op.create_index("ix_gyms_id", "gyms", ["id"])

    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column(
            "membership_type",
            sa.String(),
            nullable=False,
            server_default="Monthly",
        ),
        sa.Column("payment_due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="Active",
        ),
        sa.Column("deleted_at", TIMESTAMP, nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["gym_id"],
            ["gyms.id"],
            name="fk_members_gym_id_gyms",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "membership_type = 'Monthly'",
            name="ck_members_monthly_membership",
        ),
        sa.CheckConstraint(
            "status IN ('Active', 'Expired')",
            name="ck_members_valid_status",
        ),
    )

    op.create_index("ix_members_id", "members", ["id"])
    op.create_index(
        "ix_members_gym_due_date",
        "members",
        ["gym_id", "payment_due_date"],
    )
    op.create_index(
        "ix_members_gym_full_name",
        "members",
        ["gym_id", "full_name"],
    )
    op.create_index(
        "ix_members_gym_phone",
        "members",
        ["gym_id", "phone"],
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False), sa.Column(
            "membership_type",
            sa.String(),
            nullable=False,
            server_default="Monthly",
        ),
        sa.Column(
            "payment_type",
            sa.String(),
            nullable=False,
            server_default="Renewal",
        ),
        sa.Column(
            "created_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["gym_id"],
            ["gyms.id"],
            name="fk_payments_gym_id_gyms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name="fk_payments_member_id_members",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_payments_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "membership_type = 'Monthly'",
            name="ck_payments_monthly_membership",
        ),
        sa.CheckConstraint(
            "payment_type IN ('Registration', 'Renewal')",
            name="ck_payments_valid_type",
        ),
    )

    op.create_index("ix_payments_id", "payments", ["id"])
    op.create_index(
        "ix_payments_gym_payment_date",
        "payments",
        ["gym_id", "payment_date"],
    )
    op.create_index(
        "ix_payments_member_payment_date",
        "payments",
        ["member_id", "payment_date"],
    )


def _upgrade_legacy_schema() -> None:
    """Upgrade the existing legacy SQLite database safely."""

    bind = op.get_bind()

    # SQLite requires foreign keys to be disabled while rebuilding
    # tables with Alembic batch operations.
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))

    # ---------------------------------------------------------
    # GYMS
    # ---------------------------------------------------------

    gym_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("gyms")
    }

    if "created_at" not in gym_columns:
        op.add_column(
            "gyms",
            sa.Column("created_at", TIMESTAMP, nullable=True),
        )

    if "updated_at" not in gym_columns:
        op.add_column(
            "gyms",
            sa.Column("updated_at", TIMESTAMP, nullable=True),
        )

    bind.execute(
        sa.text(
            """
            UPDATE gyms
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE gyms
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL
            """
        )
    )

    gym = (
        bind.execute(
            sa.text(
                """
                SELECT id, currency
                FROM gyms
                ORDER BY id
                LIMIT 1
                """
            )
        )
        .mappings()
        .first()
    )

    if gym is None:
        bind.execute(
            sa.text(
                """
                INSERT INTO gyms
                    (name, currency, registration_fee, monthly_fee)
                VALUES
                    ('My Gym', 'GHS', 0, 0)
                """
            )
        )

        gym = (
            bind.execute(
                sa.text(
                    """
                    SELECT id, currency
                    FROM gyms
                    ORDER BY id
                    LIMIT 1
                    """
                )
            )
            .mappings()
            .one()
        )

    gym_id = gym["id"]
    currency = gym["currency"] or "GHS"

    # ---------------------------------------------------------
    # MEMBERS
    # ---------------------------------------------------------
    member_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("members")
    }

    if "gym_id" not in member_columns:
        op.add_column(
            "members",
            sa.Column("gym_id", sa.Integer(), nullable=True),
        )

    if "deleted_at" not in member_columns:
        op.add_column(
            "members",
            sa.Column("deleted_at", TIMESTAMP, nullable=True),
        )

    if "created_at" not in member_columns:
        op.add_column(
            "members",
            sa.Column("created_at", TIMESTAMP, nullable=True),
        )

    if "updated_at" not in member_columns:
        op.add_column(
            "members",
            sa.Column("updated_at", TIMESTAMP, nullable=True),
        )

    bind.execute(
        sa.text(
            """
            UPDATE members
            SET gym_id = :gym_id
            WHERE gym_id IS NULL
            """
        ),
        {"gym_id": gym_id},
    )

    bind.execute(
        sa.text(
            """
            UPDATE members
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE members
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL
            """
        )
    )

    # ---------------------------------------------------------
    # PAYMENTS
    # ---------------------------------------------------------

    payment_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("payments")
    }

    if "gym_id" not in payment_columns:
        op.add_column(
            "payments",
            sa.Column("gym_id", sa.Integer(), nullable=True),
        )

    if "currency" not in payment_columns:
        op.add_column(
            "payments",
            sa.Column("currency", sa.String(length=3), nullable=True),
        )

    if "created_at" not in payment_columns:
        op.add_column(
            "payments",
            sa.Column("created_at", TIMESTAMP, nullable=True),
        )

    if "updated_at" not in payment_columns:
        op.add_column(
            "payments",
            sa.Column("updated_at", TIMESTAMP, nullable=True),
        )

    bind.execute(
        sa.text(
            """
            UPDATE payments
            SET gym_id = :gym_id
            WHERE gym_id IS NULL
            """
        ),
        {"gym_id": gym_id},
    )

    bind.execute(
        sa.text(
            """
            UPDATE payments
            SET currency = :currency
            WHERE currency IS NULL
            """
        ),
        {"currency": currency},
    )

    bind.execute(
        sa.text(
            """
            UPDATE payments
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE payments
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL
            """
        )
    )

    # ---------------------------------------------------------
    # SAFETY CHECKS BEFORE MAKING COLUMNS NOT NULL
    # ---------------------------------------------------------

    remaining_members = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM members WHERE gym_id IS NULL"
        )
    ).scalar_one()

    if remaining_members:
        raise RuntimeError(
            f"Migration aborted: {remaining_members} member(s) "
            "have NULL gym_id."
        )

    remaining_payments = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM payments WHERE gym_id IS NULL"
        )
    ).scalar_one()

    if remaining_payments:
        raise RuntimeError(
            f"Migration aborted: {remaining_payments} payment(s) "
            "have NULL gym_id."
        )

    remaining_currency = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM payments WHERE currency IS NULL"
        )
    ).scalar_one()

    if remaining_currency:
        raise RuntimeError(
            f"Migration aborted: {remaining_currency} payment(s) "
            "have NULL currency."
        )

    # ---------------------------------------------------------
    # PRESERVE PAYMENTS WHOSE MEMBER WAS LEGACY-DELETED
    # ---------------------------------------------------------

    orphaned_payments = bind.execute(
        sa.text(
            """
            SELECT id, member_name, payment_date
            FROM payments
            WHERE member_id IS NULL
            """
        )
    ).mappings()

    for payment in orphaned_payments:
        result = bind.execute(
            sa.text(
                """
                INSERT INTO members (
                    gym_id,
                    full_name,
                    phone,
                    registration_date,
                    membership_type,
                    payment_due_date,
                    status,
                    deleted_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    :gym_id,
                    :full_name,
                    :phone,
                    :payment_date,
                    'Monthly',
                    :payment_date,
                    'Expired',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "gym_id": gym_id,
                "full_name": payment["member_name"],
                "phone": f"legacy-payment-{payment['id']}",
                "payment_date": payment["payment_date"],
            },
        )

        bind.execute(
            sa.text(
                """
                UPDATE payments
                SET member_id = :member_id
                WHERE id = :payment_id
                """
            ),
            {
                "member_id": result.lastrowid,
                "payment_id": payment["id"],
            },
        )

    # ---------------------------------------------------------
    # HARDEN GYMS
    # ---------------------------------------------------------

    with op.batch_alter_table(
        "gyms",
        recreate="always",
    ) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.alter_column(
            "updated_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.create_check_constraint(
            "ck_gyms_registration_fee_nonnegative",
            "registration_fee >= 0",
        )

        batch_op.create_check_constraint(
            "ck_gyms_monthly_fee_nonnegative",
            "monthly_fee >= 0",
        )

    # ---------------------------------------------------------
    # HARDEN MEMBERS
    # ---------------------------------------------------------

    with op.batch_alter_table(
        "members",
        recreate="always",
    ) as batch_op:
        batch_op.alter_column(
            "gym_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

        batch_op.alter_column(
            "created_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.alter_column(
            "updated_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.create_foreign_key(
            "fk_members_gym_id_gyms",
            "gyms",
            ["gym_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        batch_op.create_check_constraint(
            "ck_members_monthly_membership",
            "membership_type = 'Monthly'",
        )

        batch_op.create_check_constraint(
            "ck_members_valid_status",
            "status IN ('Active', 'Expired')",
        )

        batch_op.create_index(
            "ix_members_gym_due_date",
            ["gym_id", "payment_due_date"],
        )

        batch_op.create_index("ix_members_gym_full_name",
                              ["gym_id", "full_name"],
                              )

        batch_op.create_index(
            "ix_members_gym_phone",
            ["gym_id", "phone"],
        )

    # ---------------------------------------------------------
    # HARDEN PAYMENTS
    # ---------------------------------------------------------

    with op.batch_alter_table(
        "payments",
        recreate="always",
    ) as batch_op:
        batch_op.alter_column(
            "gym_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

        batch_op.alter_column(
            "member_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=3),
            nullable=False,
        )

        batch_op.alter_column(
            "created_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.alter_column(
            "updated_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.create_foreign_key(
            "fk_payments_gym_id_gyms",
            "gyms",
            ["gym_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        batch_op.create_foreign_key(
            "fk_payments_member_id_members",
            "members",
            ["member_id"],
            ["id"],
            ondelete="RESTRICT",
        )

        batch_op.create_check_constraint(
            "ck_payments_amount_nonnegative",
            "amount >= 0",
        )

        batch_op.create_check_constraint(
            "ck_payments_monthly_membership",
            "membership_type = 'Monthly'",
        )

        batch_op.create_check_constraint(
            "ck_payments_valid_type",
            "payment_type IN ('Registration', 'Renewal')",
        )

        batch_op.create_index(
            "ix_payments_gym_payment_date",
            ["gym_id", "payment_date"],
        )

        batch_op.create_index(
            "ix_payments_member_payment_date",
            ["member_id", "payment_date"],
        )

    if bind.dialect.name == "sqlite":
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    """Run the migration."""

    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("gyms"):
        _create_current_schema()
    else:
        _upgrade_legacy_schema()


def downgrade() -> None:
    raise NotImplementedError(
        "0001_database_hardening is intentionally irreversible because "
        "it backfills tenant ownership and preserves historical payment data."
    )
