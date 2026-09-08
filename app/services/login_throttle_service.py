"""Transaction-safe, database-backed login throttling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import LOGIN_RATE_LIMIT_SECONDS, MAX_LOGIN_ATTEMPTS
from app.models import LoginThrottle


def _to_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _cleanup_expired(db: Session, now: datetime) -> None:
    """Delete a small bounded batch of stale, unlocked keys per login flow."""
    cutoff = now - timedelta(seconds=LOGIN_RATE_LIMIT_SECONDS * 2)
    stale_ids = [
        row.id
        for row in (
            db.query(LoginThrottle.id)
            .filter(
                LoginThrottle.last_attempt_at < cutoff,
                LoginThrottle.locked_until.is_(None),
            )
            .order_by(LoginThrottle.last_attempt_at.asc())
            .limit(100)
            .all()
        )
    ]
    if stale_ids:
        db.query(LoginThrottle).filter(LoginThrottle.id.in_(stale_ids)).delete(
            synchronize_session=False
        )


def acquire_login_throttle(
    db: Session, *, key_hash: str, now: datetime
) -> LoginThrottle | None:
    """Lock a throttle key and return None while its throttle is active.

    PostgreSQL row locking serializes all attempts for the same key. A unique
    key plus savepoint handles the first-attempt creation race without relying
    on process-local state. The returned row remains locked until the caller
    commits or rolls back its login transaction.
    """
    _cleanup_expired(db, now)
    throttle = (
        db.query(LoginThrottle)
        .filter(LoginThrottle.key_hash == key_hash)
        .with_for_update()
        .first()
    )
    if throttle is None:
        try:
            with db.begin_nested():
                throttle = LoginThrottle(
                    key_hash=key_hash,
                    failure_count=0,
                    window_started_at=now,
                    last_attempt_at=now,
                )
                db.add(throttle)
                db.flush()
        except IntegrityError:
            throttle = (
                db.query(LoginThrottle)
                .filter(LoginThrottle.key_hash == key_hash)
                .with_for_update()
                .one()
            )

    if throttle.locked_until is not None and _to_utc(throttle.locked_until) > now:
        db.rollback()
        return None

    if throttle.locked_until is not None:
        throttle.failure_count = 0
        throttle.locked_until = None
        throttle.window_started_at = now
    return throttle


def record_failed_login(db: Session, throttle: LoginThrottle, now: datetime) -> None:
    throttle.failure_count += 1
    throttle.last_attempt_at = now
    if throttle.failure_count >= MAX_LOGIN_ATTEMPTS:
        throttle.locked_until = now + timedelta(seconds=LOGIN_RATE_LIMIT_SECONDS)
    db.commit()


def clear_login_throttle(db: Session, throttle: LoginThrottle) -> None:
    """Clear state only as part of the successful-login transaction."""
    db.delete(throttle)
