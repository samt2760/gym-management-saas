"""Repair payment 9 and enforce exactly one tenant-safe association.

Revision ID: 0008_payment_legacy_association
Revises: 0007_login_throttles
"""

from datetime import date

import sqlalchemy as sa
from alembic import op


revision = "0008_payment_legacy_association"
down_revision = "0007_login_throttles"
branch_labels = None
depends_on = None

PAYMENT_9_FACTS = {
    "id": 9, "member_id": None, "member_name": "saas", "amount": 200,
    "currency": "GHS", "payment_date": date(2026, 8, 28),
    "payment_type": "Registration",
}
LEGACY_SOURCE_REFERENCE = "legacy-payment-9"
LEGACY_RECORD_KIND = "ARCHIVED_LEGACY_MEMBER"
LEGACY_REASON_CODE = "UNLINKED_HISTORICAL_PAYMENT"
CHECK_NAME = "ck_payments_exactly_one_association"


def _require_postgresql(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Mission 9 requires PostgreSQL transactional DDL.")


def _assert_payment_9(bind: sa.Connection) -> dict[str, object]:
    row = bind.execute(sa.text("""
        SELECT id, gym_id, member_id, member_name, amount, currency,
               payment_date, payment_type, legacy_member_record_id
        FROM payments WHERE id = 9 FOR UPDATE
    """)).mappings().one_or_none()
    if row is None or any(row[key] != value for key, value in PAYMENT_9_FACTS.items()):
        raise RuntimeError("Payment 9 does not have the approved historical facts.")
    if row["legacy_member_record_id"] is not None:
        raise RuntimeError("Payment 9 already has an unexpected legacy association.")
    return dict(row)


def _assert_only_payment_9_violates(bind: sa.Connection) -> None:
    violating_ids = bind.execute(sa.text("""
        SELECT id FROM payments
        WHERE num_nonnulls(member_id, legacy_member_record_id) <> 1
        ORDER BY id FOR UPDATE
    """)).scalars().all()
    if violating_ids != [9]:
        raise RuntimeError(
            "Payment 9 must be the sole pre-existing association invariant violation."
        )


def _legacy_record_id(bind: sa.Connection, gym_id: int) -> int:
    rows = bind.execute(sa.text("""
        SELECT id, record_kind, reason_code, created_by_user_id
        FROM legacy_member_records
        WHERE gym_id = :gym_id AND source_reference = :source_reference
        FOR UPDATE
    """), {"gym_id": gym_id, "source_reference": LEGACY_SOURCE_REFERENCE}).mappings().all()
    if not rows:
        return bind.execute(sa.text("""
            INSERT INTO legacy_member_records
                (gym_id, record_kind, reason_code, source_reference, created_by_user_id,
                 created_at, updated_at)
            VALUES
                (:gym_id, :record_kind, :reason_code, :source_reference, NULL,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
        """), {
            "gym_id": gym_id, "record_kind": LEGACY_RECORD_KIND,
            "reason_code": LEGACY_REASON_CODE,
            "source_reference": LEGACY_SOURCE_REFERENCE,
        }).scalar_one()
    if len(rows) != 1:
        raise RuntimeError("Payment 9 legacy record lookup is ambiguous.")
    record = rows[0]
    if (record["record_kind"] != LEGACY_RECORD_KIND
            or record["reason_code"] != LEGACY_REASON_CODE
            or record["created_by_user_id"] is not None):
        raise RuntimeError("Existing payment 9 legacy record is incompatible.")
    return int(record["id"])


def _assert_repair(bind: sa.Connection, gym_id: int, legacy_record_id: int) -> None:
    repaired = bind.execute(sa.text("""
        SELECT p.member_id, p.legacy_member_record_id, l.gym_id,
               l.record_kind, l.reason_code, l.source_reference
        FROM payments p
        JOIN legacy_member_records l ON l.id = p.legacy_member_record_id
        WHERE p.id = 9
    """)).mappings().one_or_none()
    expected = {
        "member_id": None, "legacy_member_record_id": legacy_record_id,
        "gym_id": gym_id, "record_kind": LEGACY_RECORD_KIND,
        "reason_code": LEGACY_REASON_CODE,
        "source_reference": LEGACY_SOURCE_REFERENCE,
    }
    if repaired is None or any(repaired[key] != value for key, value in expected.items()):
        raise RuntimeError("Payment 9 legacy association verification failed.")


def upgrade() -> None:
    bind = op.get_bind()
    _require_postgresql(bind)

    op.create_unique_constraint("uq_members_gym_id_id", "members", ["gym_id", "id"])
    op.create_unique_constraint("uq_users_gym_id_id", "users", ["gym_id", "id"])
    op.create_table(
        "legacy_member_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("record_kind", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gym_id"], ["gyms.id"], name="fk_legacy_member_records_gym_id_gyms", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gym_id", "created_by_user_id"], ["users.gym_id", "users.id"], name="fk_legacy_member_records_gym_user", ondelete="RESTRICT"),
        sa.UniqueConstraint("gym_id", "id", name="uq_legacy_member_records_gym_id_id"),
        sa.UniqueConstraint("gym_id", "source_reference", name="uq_legacy_member_records_gym_source"),
        sa.CheckConstraint("record_kind = 'ARCHIVED_LEGACY_MEMBER'", name="ck_legacy_member_records_kind"),
        sa.CheckConstraint("reason_code = 'UNLINKED_HISTORICAL_PAYMENT'", name="ck_legacy_member_records_reason"),
    )
    op.create_index("ix_legacy_member_records_gym_id", "legacy_member_records", ["gym_id"])
    op.add_column("payments", sa.Column("legacy_member_record_id", sa.Integer(), nullable=True))
    op.create_index("ix_payments_legacy_member_record_id", "payments", ["legacy_member_record_id"])
    op.create_foreign_key("fk_payments_gym_member", "payments", "members", ["gym_id", "member_id"], ["gym_id", "id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_payments_gym_legacy_member_record", "payments", "legacy_member_records", ["gym_id", "legacy_member_record_id"], ["gym_id", "id"], ondelete="RESTRICT")
    op.execute(sa.text(f"""
        ALTER TABLE payments ADD CONSTRAINT {CHECK_NAME}
        CHECK (num_nonnulls(member_id, legacy_member_record_id) = 1) NOT VALID
    """))

    payment = _assert_payment_9(bind)
    _assert_only_payment_9_violates(bind)
    legacy_record_id = _legacy_record_id(bind, int(payment["gym_id"]))
    bind.execute(sa.text("""
        UPDATE payments SET legacy_member_record_id = :legacy_record_id
        WHERE id = 9 AND member_id IS NULL AND legacy_member_record_id IS NULL
    """), {"legacy_record_id": legacy_record_id})
    _assert_repair(bind, int(payment["gym_id"]), legacy_record_id)
    op.execute(sa.text(f"ALTER TABLE payments VALIDATE CONSTRAINT {CHECK_NAME}"))
    validated = bind.execute(sa.text("""
        SELECT convalidated FROM pg_constraint
        WHERE conrelid = 'payments'::regclass AND conname = :constraint_name
    """), {"constraint_name": CHECK_NAME}).scalar_one_or_none()
    if validated is not True:
        raise RuntimeError("Payment association constraint was not validated.")


def downgrade() -> None:
    bind = op.get_bind()
    _require_postgresql(bind)
    op.drop_constraint(CHECK_NAME, "payments", type_="check")
    op.drop_constraint("fk_payments_gym_legacy_member_record", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_gym_member", "payments", type_="foreignkey")
    op.drop_index("ix_payments_legacy_member_record_id", table_name="payments")
    op.drop_column("payments", "legacy_member_record_id")
    op.drop_index("ix_legacy_member_records_gym_id", table_name="legacy_member_records")
    op.drop_table("legacy_member_records")
    op.drop_constraint("uq_users_gym_id_id", "users", type_="unique")
    op.drop_constraint("uq_members_gym_id_id", "members", type_="unique")
