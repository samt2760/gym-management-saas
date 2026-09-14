"""Enforce transaction-scoped tenant isolation with PostgreSQL RLS.

Revision ID: 0009_postgresql_tenant_rls
Revises: 0008_payment_legacy_association
Create Date: 2026-09-13

The application stamps ``app.current_gym_id`` with ``set_config(..., true)``
at the start of every authenticated SQLAlchemy transaction.  ``true`` makes
the setting transaction-local, which prevents a pooled connection from
carrying one request's tenant identity into the next request.

Only tables with a direct, authoritative ``gym_id`` are covered here.  The
identity/session/reset and login-throttle tables are deliberately excluded:
they are needed to authenticate a request before a trusted tenant can be
resolved and do not have a direct tenant key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_postgresql_tenant_rls"
down_revision = "0008_payment_legacy_association"
branch_labels = None
depends_on = None


# These are the tenant-owned tables in the current schema.  Keep the list
# explicit so a future tenant-owned table requires a conscious RLS decision.
TENANT_TABLES = (
    ("gyms", "id"),
    ("members", "gym_id"),
    ("payments", "gym_id"),
    ("audit_logs", "gym_id"),
    ("legacy_member_records", "gym_id"),
)
POLICY_NAME = "tenant_gym_isolation"


def _tenant_predicate(column_name: str) -> str:
    """Return the fail-closed predicate for a direct tenant-key column."""

    return (
        f"{column_name} = "
        "NULLIF(current_setting('app.current_gym_id', true), '')::integer"
    )


def upgrade() -> None:
    """Enable, force, and policy-protect every direct tenant-owned table."""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite is retained only for isolated application tests and has no
        # PostgreSQL RLS equivalent.  Production migrations require PostgreSQL.
        return

    for table_name, tenant_column in TENANT_TABLES:
        predicate = _tenant_predicate(tenant_column)
        op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY {POLICY_NAME} ON {table_name} "
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )
        )


def downgrade() -> None:
    """Remove only the policies and RLS flags created by this revision."""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table_name, _tenant_column in reversed(TENANT_TABLES):
        op.execute(sa.text(f"DROP POLICY {POLICY_NAME} ON {table_name}"))
        op.execute(sa.text(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY"))
