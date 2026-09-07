"""Shared persistence primitives."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-managed audit fields."""
    return datetime.now(UTC)


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
