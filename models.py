from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Gym(Base):
    __tablename__ = "gyms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="My Gym")
    currency = Column(String, nullable=False, default="GHS")
    registration_fee = Column(Integer, nullable=False, default=0)
    monthly_fee = Column(Integer, nullable=False, default=0)


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    registration_date = Column(Date, nullable=False)
    membership_type = Column(String, nullable=False, default="Monthly")
    payment_due_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default="Active")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    member_name = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    payment_date = Column(Date, nullable=False)
    membership_type = Column(String, nullable=False, default="Monthly")
    payment_type = Column(String, nullable=False, default="Renewal")
