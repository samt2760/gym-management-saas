from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Member(TimestampMixin, Base):
    __tablename__ = "members"
    __table_args__ = (
        CheckConstraint("membership_type = 'Monthly'",
                        name="ck_members_monthly_membership"),
        CheckConstraint("status IN ('Active', 'Expired', 'Frozen', 'Cancelled')",
                        name="ck_members_valid_status"),
        Index("ix_members_gym_due_date", "gym_id", "payment_due_date"),
        Index("ix_members_gym_full_name", "gym_id", "full_name"),
        Index("ix_members_gym_phone", "gym_id", "phone"),
    )

    id = Column(Integer, primary_key=True, index=True)
    gym_id = Column(Integer, ForeignKey(
        "gyms.id", ondelete="RESTRICT"), nullable=False)
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    registration_date = Column(Date, nullable=False)
    membership_type = Column(String, nullable=False, default="Monthly")
    payment_due_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default="Active")
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    gym = relationship("Gym", back_populates="members")
    payments = relationship("Payment", back_populates="member")
