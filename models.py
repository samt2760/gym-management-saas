from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ============================================================
# GYM
# ============================================================

class Gym(Base):
    __tablename__ = "gyms"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(
        String,
        nullable=False,
        default="My Gym",
    )

    currency = Column(
        String(3),
        nullable=False,
        default="GHS",
    )

    registration_fee = Column(
        Integer,
        nullable=False,
        default=0,
    )

    monthly_fee = Column(
        Integer,
        nullable=False,
        default=0,
    )

    created_at = Column(
        DateTime,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "registration_fee >= 0",
            name="ck_gyms_registration_fee_nonnegative",
        ),
        CheckConstraint(
            "monthly_fee >= 0",
            name="ck_gyms_monthly_fee_nonnegative",
        ),
    )


# ============================================================
# USER
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    gym_id = Column(
        Integer,
        ForeignKey(
            "gyms.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    email = Column(
        String,
        nullable=False,
    )

    password_hash = Column(
        String,
        nullable=False,
    )

    role = Column(
        String,
        nullable=False,
        default="owner",
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'staff')",
            name="ck_users_valid_role",
        ),
        Index(
            "ix_users_gym_id",
            "gym_id",
        ),
        Index(
            "ix_users_gym_email",
            "gym_id",
            "email",
            unique=True,
        ),
    )


# ============================================================
# MEMBER
# ============================================================

class Member(Base):
    __tablename__ = "members"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    gym_id = Column(
        Integer,
        ForeignKey(
            "gyms.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    full_name = Column(
        String,
        nullable=False,
    )

    phone = Column(
        String,
        nullable=False,
    )

    email = Column(
        String,
        nullable=True,
    )

    date_of_birth = Column(
        Date,
        nullable=True,
    )

    registration_date = Column(
        Date,
        nullable=False,
    )

    membership_type = Column(
        String,
        nullable=False,
        default="Monthly",
    )

    payment_due_date = Column(
        Date,
        nullable=False,
    )

    status = Column(
        String,
        nullable=False,
        default="Active",
    )

    deleted_at = Column(
        DateTime,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "membership_type = 'Monthly'",
            name="ck_members_monthly_membership",
        ),
        CheckConstraint(
            "status IN ('Active', 'Expired')",
            name="ck_members_valid_status",
        ),
        Index("ix_members_gym_due_date",
              "gym_id",
              "payment_due_date",
              ),
        Index(
            "ix_members_gym_full_name",
            "gym_id",
            "full_name",
        ),
        Index(
            "ix_members_gym_phone",
            "gym_id",
            "phone",
        ),
    )


# ============================================================
# PAYMENT
# ============================================================

class Payment(Base):
    __tablename__ = "payments"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    member_id = Column(
        Integer,
        ForeignKey(
            "members.id",
            ondelete="RESTRICT",
            name="fk_payments_member_id_members",
        ),
        nullable=True,
    )

    gym_id = Column(
        Integer,
        ForeignKey(
            "gyms.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

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

    created_at = Column(
        DateTime,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_payments_amount_nonnegative",
        ),
        CheckConstraint(
            "membership_type = 'Monthly'",
            name="ck_payments_monthly_membership",
        ),
        CheckConstraint(
            "payment_type IN ('Registration', 'Renewal')",
            name="ck_payments_valid_type",
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
    )
