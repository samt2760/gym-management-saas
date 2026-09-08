"""Database-backed state for login failure throttling."""

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint

from app.core.database import Base
from app.models.mixins import TimestampMixin


class LoginThrottle(TimestampMixin, Base):
    __tablename__ = "login_throttles"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_login_throttles_key_hash"),
        Index("ix_login_throttles_last_attempt_at", "last_attempt_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    key_hash = Column(String(64), nullable=False)
    failure_count = Column(Integer, nullable=False, default=0)
    window_started_at = Column(DateTime(timezone=True), nullable=False)
    last_attempt_at = Column(DateTime(timezone=True), nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
