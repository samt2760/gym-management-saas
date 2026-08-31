from sqlalchemy import CheckConstraint, Column, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Gym(TimestampMixin, Base):
    __tablename__ = "gyms"
    __table_args__ = (
        CheckConstraint("registration_fee >= 0", name="ck_gyms_registration_fee_nonnegative"),
        CheckConstraint("monthly_fee >= 0", name="ck_gyms_monthly_fee_nonnegative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="My Gym")
    currency = Column(String, nullable=False, default="GHS")
    registration_fee = Column(Integer, nullable=False, default=0)
    monthly_fee = Column(Integer, nullable=False, default=0)

    members = relationship("Member", back_populates="gym")
    payments = relationship("Payment", back_populates="gym")
    users = relationship("User", back_populates="gym")
