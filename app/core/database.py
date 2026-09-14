"""SQLAlchemy setup and compatibility migration support."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database_settings import DATABASE_CONNECT_TIMEOUT_SECONDS, DATABASE_URL
from app.core.tenant_context import (
    _set_connection_tenant_context,
    session_tenant_gym_id,
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if not DATABASE_URL.startswith("sqlite"):
    connect_args["connect_timeout"] = DATABASE_CONNECT_TIMEOUT_SECONDS
# The shared in-memory URL is used by the isolated test suite. File-backed
# SQLite and non-SQLite deployments retain normal SQLAlchemy pooling behavior.
if DATABASE_URL == "sqlite://":
    engine_options["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, **engine_options)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(SessionLocal, "after_begin")
def stamp_tenant_context_at_transaction_start(
    _session,
    _transaction,
    connection,
) -> None:
    """Stamp trusted tenant state into every PostgreSQL session transaction."""

    gym_id = session_tenant_gym_id(_session)
    if gym_id is not None:
        _set_connection_tenant_context(connection, gym_id)


Base = declarative_base()
