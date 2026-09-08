"""Durable, tenant-scoped audit records for sensitive application mutations."""

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, String

from app.core.database import Base
from app.models.mixins import TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_gym_created_at", "gym_id", "created_at"),
        Index("ix_audit_logs_actor_created_at", "actor_user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    gym_id = Column(
        Integer,
        ForeignKey("gyms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(Integer, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
