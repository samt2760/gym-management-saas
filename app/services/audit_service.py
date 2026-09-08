"""Helpers for recording transaction-bound, non-sensitive audit events."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    *,
    gym_id: int,
    action: str,
    resource_type: str,
    resource_id: int | None,
    actor: User | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit event to the caller's transaction without committing it."""
    event = AuditLog(
        gym_id=gym_id,
        actor_user_id=actor.id if actor is not None else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )
    db.add(event)
    return event


def audit_records_for_user(db: Session, user: User) -> list[AuditLog]:
    """Return only the authenticated user's tenant audit records for future UI use."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.gym_id == user.gym_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .all()
    )
