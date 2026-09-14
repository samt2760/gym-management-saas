"""Align authentication token columns and expiry indexes.

Revision ID: 0004_align_authentication_token_columns
Revises: 0003_align_authentication_schema
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_align_authentication_token_columns"
down_revision = "0003_align_authentication_schema"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    # Alembic creates its version table as VARCHAR(32) by default.  This
    # revision identifier is longer than that default, so widen the metadata
    # column before Alembic records this revision at the end of the upgrade.
    # Existing deployments already use VARCHAR(128); this makes a fresh chain
    # compatible with that established schema without touching application data.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )

    if _table_exists("user_sessions"):
        with op.batch_alter_table("user_sessions", recreate="always") as batch_op:
            batch_op.alter_column(
                "token_hash",
                existing_type=sa.String(length=128),
                type_=sa.String(length=255),
            )
            batch_op.alter_column(
                "user_agent",
                existing_type=sa.String(length=255),
                type_=sa.String(length=500),
            )
            batch_op.alter_column(
                "ip_address",
                existing_type=sa.String(length=64),
                type_=sa.String(length=45),
            )

        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("user_sessions")
        }
        if "ix_user_sessions_expires_at" not in indexes:
            op.create_index(
                "ix_user_sessions_expires_at",
                "user_sessions",
                ["expires_at"],
            )

    if _table_exists("password_reset_tokens"):
        with op.batch_alter_table(
            "password_reset_tokens",
            recreate="always",
        ) as batch_op:
            batch_op.alter_column(
                "token_hash",
                existing_type=sa.String(length=128),
                type_=sa.String(length=255),
            )

        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("password_reset_tokens")
        }
        if "ix_password_reset_tokens_expires_at" not in indexes:
            op.create_index(
                "ix_password_reset_tokens_expires_at",
                "password_reset_tokens",
                ["expires_at"],
            )


def downgrade() -> None:
    if _table_exists("user_sessions"):
        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("user_sessions")
        }
        if "ix_user_sessions_expires_at" in indexes:
            op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
        with op.batch_alter_table("user_sessions", recreate="always") as batch_op:
            batch_op.alter_column(
                "token_hash",
                existing_type=sa.String(length=255),
                type_=sa.String(length=128),
            )
            batch_op.alter_column(
                "user_agent",
                existing_type=sa.String(length=500),
                type_=sa.String(length=255),
            )
            batch_op.alter_column(
                "ip_address",
                existing_type=sa.String(length=45),
                type_=sa.String(length=64),
            )

    if _table_exists("password_reset_tokens"):
        indexes = {
            index["name"]
            for index in sa.inspect(op.get_bind()).get_indexes("password_reset_tokens")
        }
        if "ix_password_reset_tokens_expires_at" in indexes:
            op.drop_index(
                "ix_password_reset_tokens_expires_at",
                table_name="password_reset_tokens",
            )
        with op.batch_alter_table(
            "password_reset_tokens",
            recreate="always",
        ) as batch_op:
            batch_op.alter_column(
                "token_hash",
                existing_type=sa.String(length=255),
                type_=sa.String(length=128),
            )
