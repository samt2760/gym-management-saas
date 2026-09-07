from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import app.models  # noqa: F401
from app.core.database import Base

config = context.config

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is required for Alembic."
    )
config.set_main_option(
    "sqlalchemy.url",
    database_url.replace("%", "%%"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


def include_object(
    object,
    name,
    type_,
    reflected,
    compare_to,
):
    """
    Ignore known legacy schema differences.

    The payments table already has the correct foreign-key behavior
    in the database:

        payments.gym_id    -> gyms.id    ON DELETE RESTRICT
        payments.member_id -> members.id ON DELETE RESTRICT

    The existing database constraints are unnamed, while the current
    SQLAlchemy model uses explicit names.

    Alembic would otherwise continuously report these as remove/add
    operations even though the actual database behavior is correct.

    The legacy users role CHECK constraint is also intentionally
    ignored because the application now supports the current role set.
    """

    # Ignore all foreign-key comparison operations on payments.
    #
    # This deliberately handles BOTH sides:
    #   reflected=True  -> existing database FK
    #   reflected=False -> SQLAlchemy model FK
    #
    # This prevents Alembic from trying to replace equivalent
    # legacy constraints merely because their names differ.
    if (
        type_ == "foreign_key_constraint"
        and getattr(object, "table", None) is not None
        and object.table.name == "payments"
    ):
        return False

    # Ignore the legacy users role constraint.
    return not (
        type_ == "check_constraint"
        and reflected
        and name == "ck_users_valid_role"
    )


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named"
        },
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(
            config.config_ini_section,
            {},
        ),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
