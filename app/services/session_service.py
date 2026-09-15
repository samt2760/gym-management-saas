"""Session lifecycle operations shared by browser and operator workflows."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.user import UserSession


def revoke_all_user_sessions(db: Session, user_id: int, *, commit: bool = True) -> None:
    """Mark every active session for one user as revoked."""
    now = datetime.now(UTC)
    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .all()
    )
    for session in sessions:
        session.revoked_at = now
    if commit:
        db.commit()
