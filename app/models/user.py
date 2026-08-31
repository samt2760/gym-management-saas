from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

import bcrypt
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Role(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    RECEPTIONIST = "RECEPTIONIST"
    TRAINER = "TRAINER"


class Permission(str, Enum):
    MEMBERS_VIEW = "members.view"
    MEMBERS_CREATE = "members.create"
    MEMBERS_EDIT = "members.edit"
    MEMBERS_DELETE = "members.delete"
    PAYMENTS_VIEW = "payments.view"
    PAYMENTS_CREATE = "payments.create"
    PAYMENTS_REFUND = "payments.refund"
    REPORTS_VIEW = "reports.view"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_EDIT = "settings.edit"
    STAFF_VIEW = "staff.view"
    STAFF_MANAGE = "staff.manage"
    ATTENDANCE_VIEW = "attendance.view"
    ATTENDANCE_MANAGE = "attendance.manage"


ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.OWNER.value: {
        permission.value for permission in Permission
    },
    Role.ADMIN.value: {
        permission.value for permission in Permission
    },
    Role.MANAGER.value: {
        Permission.MEMBERS_VIEW.value,
        Permission.MEMBERS_CREATE.value,
        Permission.MEMBERS_EDIT.value,
        Permission.PAYMENTS_VIEW.value,
        Permission.PAYMENTS_CREATE.value,
        Permission.REPORTS_VIEW.value,
        Permission.SETTINGS_VIEW.value,
        Permission.STAFF_VIEW.value,
        Permission.ATTENDANCE_VIEW.value,
        Permission.ATTENDANCE_MANAGE.value,
    },
    Role.RECEPTIONIST.value: {
        Permission.MEMBERS_VIEW.value,
        Permission.MEMBERS_CREATE.value,
        Permission.MEMBERS_EDIT.value,
        Permission.PAYMENTS_VIEW.value,
        Permission.PAYMENTS_CREATE.value,
        Permission.ATTENDANCE_VIEW.value,
        Permission.ATTENDANCE_MANAGE.value,
        Permission.STAFF_VIEW.value,
    },
    Role.TRAINER.value: {
        Permission.MEMBERS_VIEW.value,
        Permission.REPORTS_VIEW.value,
        Permission.ATTENDANCE_VIEW.value,
        Permission.ATTENDANCE_MANAGE.value,
    },
}


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    gym_id = Column(Integer, ForeignKey("gyms.id", ondelete="RESTRICT"), nullable=False, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    role = Column(String(32), nullable=False, default=Role.OWNER.value, index=True)
    is_superuser = Column(Boolean, nullable=False, default=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    gym = relationship("Gym", back_populates="users")
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan")

    @property
    def permissions(self) -> set[str]:
        if self.is_superuser:
            return {permission.value for permission in Permission}
        return set(ROLE_PERMISSIONS.get(self.role or Role.OWNER.value, set()))

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or self.is_superuser


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    user_agent = Column(String(255), nullable=True)
    ip_address = Column(String(64), nullable=True)

    user = relationship("User", back_populates="sessions")


class PasswordResetToken(TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="reset_tokens")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("$2b$"):
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == password_hash


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
