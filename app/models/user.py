from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

import bcrypt
from pwdlib import PasswordHash
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

password_hasher = PasswordHash.recommended()


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


ROLE_PERMISSIONS = {
    Role.OWNER.value: {permission.value for permission in Permission},
    Role.ADMIN.value: {
        Permission.MEMBERS_VIEW.value,
        Permission.MEMBERS_CREATE.value,
        Permission.MEMBERS_EDIT.value,
        Permission.MEMBERS_DELETE.value,
        Permission.PAYMENTS_VIEW.value,
        Permission.PAYMENTS_CREATE.value,
        Permission.PAYMENTS_REFUND.value,
        Permission.REPORTS_VIEW.value,
        Permission.SETTINGS_VIEW.value,
        Permission.SETTINGS_EDIT.value,
        Permission.STAFF_VIEW.value,
        Permission.STAFF_MANAGE.value,
        Permission.ATTENDANCE_VIEW.value,
        Permission.ATTENDANCE_MANAGE.value,
    },
    Role.MANAGER.value: {
        Permission.MEMBERS_VIEW.value,
        Permission.MEMBERS_CREATE.value,
        Permission.MEMBERS_EDIT.value,
        Permission.PAYMENTS_VIEW.value,
        Permission.PAYMENTS_CREATE.value,
        Permission.REPORTS_VIEW.value,
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
    },
    Role.TRAINER.value: {
        Permission.MEMBERS_VIEW.value,
        Permission.ATTENDANCE_VIEW.value,
        Permission.ATTENDANCE_MANAGE.value,
    },
}


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$argon2"):
        return password_hasher.verify(password, stored_hash)

    if stored_hash.startswith("$2b$"):
        return bcrypt.checkpw(
            password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )

    return False


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("gym_id", "id", name="uq_users_gym_id_id"),)

    id = Column(Integer, primary_key=True, index=True)

    gym_id = Column(
        Integer,
        ForeignKey("gyms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    username = Column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )

    email = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    password_hash = Column(
        String(255),
        nullable=False,
    )

    status = Column(
        String(20),
        nullable=False,
        default="active",
    )

    role = Column(
        String(32),
        nullable=False,
        default=Role.OWNER.value,
        index=True,
    )

    is_superuser = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    last_login = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    gym = relationship(
        "Gym",
        back_populates="users",
    )
    sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    password_reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    legacy_member_records = relationship(
        "LegacyMemberRecord",
        back_populates="created_by_user",
        foreign_keys="LegacyMemberRecord.created_by_user_id",
    )

    def has_permission(self, permission: Permission | str) -> bool:
        if self.is_superuser:
            return True

        permission_value = (
            permission.value if isinstance(permission, Permission) else permission
        )

        role = self.role.upper()

        return permission_value in ROLE_PERMISSIONS.get(role, set())

    def is_active_user(self) -> bool:
        return self.status.lower() == "active"


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token_hash = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    revoked_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    user_agent = Column(
        String(500),
        nullable=True,
    )

    ip_address = Column(
        String(45),
        nullable=True,
    )

    user = relationship(
        "User",
        back_populates="sessions",
    )

    def is_valid(self) -> bool:
        now = datetime.now(UTC)

        if self.revoked_at is not None:
            return False

        return self.expires_at > now


class PasswordResetToken(TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token_hash = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    used_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    user = relationship(
        "User",
        back_populates="password_reset_tokens",
    )

    def is_valid(self) -> bool:
        now = datetime.now(UTC)

        if self.used_at is not None:
            return False

        return self.expires_at > now
