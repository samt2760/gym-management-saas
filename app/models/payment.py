from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_payments_amount_nonnegative",
        ),
        CheckConstraint(
            "status IN ('Completed', 'Voided')",
            name="ck_payments_valid_status",
        ),
        CheckConstraint(
            "membership_type = 'Monthly'",
            name="ck_payments_monthly_membership",
        ),
        CheckConstraint(
            "payment_type IN ('Registration', 'Renewal')",
            name="ck_payments_valid_type",
        ),
        # Equivalent to the PostgreSQL num_nonnulls check in the release
        # migration, while remaining executable in SQLite application tests.
        CheckConstraint(
            "(member_id IS NOT NULL AND legacy_member_record_id IS NULL) OR "
            "(member_id IS NULL AND legacy_member_record_id IS NOT NULL)",
            name="ck_payments_exactly_one_association",
        ),
        ForeignKeyConstraint(
            ["gym_id", "member_id"],
            ["members.gym_id", "members.id"],
            name="fk_payments_gym_member",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["gym_id", "legacy_member_record_id"],
            ["legacy_member_records.gym_id", "legacy_member_records.id"],
            name="fk_payments_gym_legacy_member_record",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_payments_gym_payment_date",
            "gym_id",
            "payment_date",
        ),
        Index(
            "ix_payments_member_payment_date",
            "member_id",
            "payment_date",
        ),
        Index(
            "uq_payments_gym_idempotency_key",
            "gym_id",
            "idempotency_key",
            unique=True,
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    gym_id = Column(
        Integer,
        ForeignKey(
            "gyms.id",
            name="fk_payments_gym_id_gyms",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    member_id = Column(
        Integer,
        ForeignKey(
            "members.id",
            name="fk_payments_member_id_members",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    legacy_member_record_id = Column(Integer, nullable=True)

    member_name = Column(
        String,
        nullable=False,
    )

    amount = Column(
        Integer,
        nullable=False,
    )

    currency = Column(
        String(3),
        nullable=False,
    )

    payment_date = Column(
        Date,
        nullable=False,
    )

    membership_type = Column(
        String,
        nullable=False,
        default="Monthly",
    )

    payment_type = Column(
        String,
        nullable=False,
        default="Renewal",
    )

    # Financial rows remain in history; corrections use an explicit state.
    status = Column(
        String(16),
        nullable=False,
        default="Completed",
        server_default="Completed",
    )

    # Only retry-sensitive operations set this. Legacy and registration rows
    # remain valid with NULL keys.
    idempotency_key = Column(String(128), nullable=True)

    gym = relationship(
        "Gym",
        back_populates="payments",
    )

    member = relationship(
        "Member",
        back_populates="payments",
        foreign_keys=[member_id],
    )

    legacy_member_record = relationship(
        "LegacyMemberRecord",
        back_populates="payments",
        primaryjoin=(
            "and_(Payment.legacy_member_record_id == LegacyMemberRecord.id, "
            "Payment.gym_id == LegacyMemberRecord.gym_id)"
        ),
        foreign_keys=[legacy_member_record_id],
    )
