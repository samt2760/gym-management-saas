"""add authentication users table

Revision ID: 2aee91478c7d
Revises: 0001_database_hardening
Create Date: 2026-09-02
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "2aee91478c7d"
down_revision: str | Sequence[str] | None = "0001_database_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The users table already exists in the database.
    # This migration brings Alembic's migration history
    # into alignment with the existing schema.
    pass


def downgrade() -> None:
    # Intentionally do not drop the existing users table.
    # The table predates this migration's history entry.
    pass
