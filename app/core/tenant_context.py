"""Request-scoped trusted tenant context for PostgreSQL transactions."""

from __future__ import annotations

from contextvars import ContextVar

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

_current_gym_id: ContextVar[int | None] = ContextVar(
    "current_gym_id",
    default=None,
)

TENANT_GYM_ID_SESSION_KEY = "trusted_tenant_gym_id"


class TenantContextError(RuntimeError):
    """Raised when code attempts to establish an untrusted tenant context."""


def current_gym_id() -> int | None:
    """Return the gym id established by trusted authentication for this request."""

    return _current_gym_id.get()


def establish_tenant_context(gym_id: int | None) -> None:
    """Store a trusted authenticated user's gym id for the current request."""

    if gym_id is None or gym_id <= 0:
        raise TenantContextError("A trusted gym id is required for tenant context.")

    _current_gym_id.set(gym_id)


def clear_tenant_context() -> None:
    """Ensure a completed request cannot leave tenant state behind."""

    _current_gym_id.set(None)


def _set_connection_tenant_context(connection: Connection, gym_id: int) -> None:
    """Set PostgreSQL's transaction-local tenant GUC without SQL interpolation."""

    if connection.dialect.name != "postgresql":
        return

    connection.execute(
        text("SELECT set_config('app.current_gym_id', :gym_id_text, true)"),
        {"gym_id_text": str(gym_id)},
    )


def bind_tenant_context_to_session(session: Session, gym_id: int) -> None:
    """Bind authenticated tenant state to one request-scoped SQLAlchemy session.

    ``ContextVar`` is useful for request-local application state, but synchronous
    FastAPI dependencies and route handlers may run in different worker-context
    copies.  SQLAlchemy's ``Session.info`` survives transaction boundaries on the
    same request-scoped session, so it is the authoritative source for the
    ``after_begin`` hook that stamps each PostgreSQL transaction.
    """

    if gym_id <= 0:
        raise TenantContextError("A trusted gym id is required for tenant context.")

    session.info[TENANT_GYM_ID_SESSION_KEY] = gym_id


def session_tenant_gym_id(session: Session) -> int | None:
    """Return the trusted tenant bound to this request-scoped session."""

    gym_id = session.info.get(TENANT_GYM_ID_SESSION_KEY)
    return gym_id if isinstance(gym_id, int) and gym_id > 0 else None


def stamp_tenant_context(session: Session) -> bool:
    """Apply the request's trusted tenant context to the current transaction.

    Returns ``False`` when no authenticated tenant has been established.  This
    deliberately does not invent a default context; future RLS policies then
    fail closed.
    """

    gym_id = session_tenant_gym_id(session) or current_gym_id()
    if gym_id is None:
        return False

    _set_connection_tenant_context(session.connection(), gym_id)
    return True
