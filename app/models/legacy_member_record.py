"""Tenant-owned placeholders for reviewed historical payment associations."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class LegacyMemberRecord(TimestampMixin, Base):
    """A non-member record used only for approved historical ledger links."""

    __tablename__ = "legacy_member_records"
    __table_args__ = (
        CheckConstraint(
            "record_kind = 'ARCHIVED_LEGACY_MEMBER'",
            name="ck_legacy_member_records_kind",
        ),
        CheckConstraint(
            "reason_code = 'UNLINKED_HISTORICAL_PAYMENT'",
            name="ck_legacy_member_records_reason",
        ),
        ForeignKeyConstraint(
            ["gym_id"],
            ["gyms.id"],
            name="fk_legacy_member_records_gym_id_gyms",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["gym_id", "created_by_user_id"],
            ["users.gym_id", "users.id"],
            name="fk_legacy_member_records_gym_user",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("gym_id", "id", name="uq_legacy_member_records_gym_id_id"),
        UniqueConstraint(
            "gym_id", "source_reference", name="uq_legacy_member_records_gym_source"
        ),
        Index("ix_legacy_member_records_gym_id", "gym_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    gym_id = Column(Integer, nullable=False)
    record_kind = Column(String(32), nullable=False, default="ARCHIVED_LEGACY_MEMBER")
    reason_code = Column(
        String(64), nullable=False, default="UNLINKED_HISTORICAL_PAYMENT"
    )
    source_reference = Column(String(128), nullable=False)
    created_by_user_id = Column(Integer, nullable=True)

    gym = relationship("Gym", back_populates="legacy_member_records")
    created_by_user = relationship(
        "User",
        back_populates="legacy_member_records",
        primaryjoin=(
            "and_(LegacyMemberRecord.created_by_user_id == User.id, "
            "LegacyMemberRecord.gym_id == User.gym_id)"
        ),
        foreign_keys=[created_by_user_id],
    )
    payments = relationship(
        "Payment",
        back_populates="legacy_member_record",
        primaryjoin=(
            "and_(LegacyMemberRecord.id == Payment.legacy_member_record_id, "
            "LegacyMemberRecord.gym_id == Payment.gym_id)"
        ),
        foreign_keys="Payment.legacy_member_record_id",
    )
