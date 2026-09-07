from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_align_authentication_schema"
down_revision = "2aee91478c7d"
branch_labels = None
depends_on = None


TIMESTAMP = sa.DateTime(timezone=True)


def _table_exists(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in sa.inspect(bind).get_check_constraints(table_name)
    )


def _create_users_table(bind) -> None:
    if _table_exists(bind, "users"):
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "gym_id",
            sa.Integer(),
            sa.ForeignKey(
                "gyms.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default="OWNER",
        ),
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "last_login",
            TIMESTAMP,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP,
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    op.create_index(
        "ix_users_id",
        "users",
        ["id"],
    )
    op.create_index(
        "ix_users_gym_id",
        "users",
        ["gym_id"],
    )
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
    )
    op.create_index(
        "ix_users_username",
        "users",
        ["username"],
        unique=True,
    )
    op.create_index(
        "ix_users_role",
        "users",
        ["role"],
    )


def _upgrade_users_table(bind) -> None:
    if not _table_exists(bind, "users"):
        _create_users_table(bind)
        return

    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("users")
    }

    # ---------------------------------------------------------
    # Username
    # ---------------------------------------------------------

    if "username" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "username",
                sa.String(length=64),
                nullable=True,
            ),
        )

        users = bind.execute(
            sa.text(
                """
                SELECT id, email
                FROM users
                ORDER BY id
                """
            )
        ).mappings().all()

        used_usernames: set[str] = set()

        for user in users:
            email = (
                user["email"] or ""
            ).strip().lower()

            base_username = email.split(
                "@",
                1,
            )[0]

            if not base_username:
                base_username = (
                    f"user{user['id']}"
                )

            base_username = "".join(
                character
                for character in base_username
                if (
                    character.isalnum()
                    or character in "._-"
                )
            )

            if not base_username:
                base_username = (
                    f"user{user['id']}"
                )
                base_username = base_username[:64]

            username = base_username
            suffix = 1

            while username in used_usernames:
                suffix_text = f"-{suffix}"

                username = (
                    f"{base_username[:64 - len(suffix_text)]}"
                    f"{suffix_text}"
                )

                suffix += 1

            used_usernames.add(username)

            bind.execute(
                sa.text(
                    """
                    UPDATE users
                    SET username = :username
                    WHERE id = :user_id
                    """
                ),
                {
                    "username": username,
                    "user_id": user["id"],
                },
            )

    # ---------------------------------------------------------
    # Status
    # ---------------------------------------------------------

    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("users")
    }

    if "status" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=True,
            ),
        )

        if "is_active" in columns:
            bind.execute(
                sa.text(
                    """
                    UPDATE users
                    SET status = CASE
                        WHEN is_active = 1
                        THEN 'active'
                        ELSE 'inactive'
                    END
                    """
                )
            )
        else:
            bind.execute(
                sa.text(
                    """
                    UPDATE users
                    SET status = 'active'
                    WHERE status IS NULL
                    """
                )
            )

    # ---------------------------------------------------------
    # Superuser
    # ---------------------------------------------------------

    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("users")
    }

    if "is_superuser" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "is_superuser",
                sa.Boolean(),
                nullable=True,
            ),
        )

        bind.execute(
            sa.text(
                """
                UPDATE users
                SET is_superuser = CASE
                    WHEN role = 'OWNER'
                    THEN 1
                    ELSE 0
                END
                """
            )
        )

    # ---------------------------------------------------------
    # Last login
    # ---------------------------------------------------------

    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("users")
    }

    if "last_login" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "last_login",
                TIMESTAMP,
                nullable=True,
            ),
        )

    # ---------------------------------------------------------
    # Timestamp columns
    # ---------------------------------------------------------

    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("users")
    }

    if "created_at" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "created_at",
                TIMESTAMP,
                nullable=True,
            ),
        )

        bind.execute(
            sa.text(
                """
                UPDATE users
                SET created_at = CURRENT_TIMESTAMP
                WHERE created_at IS NULL
                """
            )
        )

    if "updated_at" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "updated_at",
                TIMESTAMP,
                nullable=True,
            ),
        )

        bind.execute(sa.text(
            """
                UPDATE users
                SET updated_at = CURRENT_TIMESTAMP
                WHERE updated_at IS NULL
                """
        )
        )

    # ---------------------------------------------------------
    # Validate backfills before making columns NOT NULL
    # ---------------------------------------------------------

    missing_username = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM users
            WHERE username IS NULL
               OR TRIM(username) = ''
            """
        )
    ).scalar_one()

    if missing_username:
        raise RuntimeError(
            f"Migration aborted: {missing_username} "
            "user(s) have no username after backfill."
        )

    missing_status = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM users
            WHERE status IS NULL
               OR TRIM(status) = ''
            """
        )
    ).scalar_one()

    if missing_status:
        raise RuntimeError(
            f"Migration aborted: {missing_status} "
            "user(s) have no status after backfill."
        )

    missing_superuser = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM users
            WHERE is_superuser IS NULL
            """
        )
    ).scalar_one()

    if missing_superuser:
        raise RuntimeError(
            f"Migration aborted: {missing_superuser} "
            "user(s) have no is_superuser value."
        )

    missing_created = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM users
            WHERE created_at IS NULL
            """
        )
    ).scalar_one()

    if missing_created:
        raise RuntimeError(
            f"Migration aborted: {missing_created} "
            "user(s) have no created_at value."
        )

    missing_updated = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM users
            WHERE updated_at IS NULL
            """
        )
    ).scalar_one()

    if missing_updated:
        raise RuntimeError(
            f"Migration aborted: {missing_updated} "
            "user(s) have no updated_at value."
        )

    # ---------------------------------------------------------
    # Rebuild SQLite users table to enforce final schema
    # ---------------------------------------------------------

    has_legacy_role_constraint = _constraint_exists(
        bind,
        "users",
        "ck_users_valid_role",
    )

    with op.batch_alter_table(
        "users",
        recreate="always",
    ) as batch_op:

        if has_legacy_role_constraint:
            batch_op.drop_constraint(
                "ck_users_valid_role",
                type_="check",
            )

        batch_op.alter_column(
            "username",
            existing_type=sa.String(length=64),
            nullable=False,
        )

        batch_op.alter_column(
            "email",
            existing_type=sa.String(),
            type_=sa.String(length=255),
            nullable=False,
        )

        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(),
            type_=sa.String(length=255),
            nullable=False,
        )

        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            nullable=False,
        )

        batch_op.alter_column(
            "role",
            existing_type=sa.String(),
            type_=sa.String(length=32),
            nullable=False,
        )

        batch_op.alter_column(
            "is_superuser",
            existing_type=sa.Boolean(),
            nullable=False,
        )

        batch_op.alter_column(
            "created_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        batch_op.alter_column(
            "updated_at",
            existing_type=TIMESTAMP,
            nullable=False,
        )

        if "is_active" in columns:
            batch_op.drop_column("is_active")

    # ---------------------------------------------------------
    # Normalize indexes
    # ---------------------------------------------------------

    inspector = sa.inspect(bind)
    for index in inspector.get_indexes("users"):
        name = index["name"]

        if name == "ix_users_gym_email":
            op.drop_index(
                name,
                table_name="users",
            )

    existing_indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("users")
    }

    if "ix_users_email" not in existing_indexes:
        op.create_index(
            "ix_users_email",
            "users",
            ["email"],
            unique=True,
        )

    if "ix_users_username" not in existing_indexes:
        op.create_index(
            "ix_users_username",
            "users",
            ["username"],
            unique=True,
        )

    if "ix_users_role" not in existing_indexes:
        op.create_index(
            "ix_users_role",
            "users",
            ["role"],
        )


def _create_auth_tables(bind) -> None:

    # ---------------------------------------------------------
    # User sessions
    # ---------------------------------------------------------

    if not _table_exists(bind, "user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                nullable=False,
            ),
            sa.Column(
                "token_hash",
                sa.String(length=128),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                TIMESTAMP,
                nullable=False,
            ),
            sa.Column(
                "revoked_at",
                TIMESTAMP,
                nullable=True,
            ),
            sa.Column(
                "user_agent",
                sa.String(length=255),
                nullable=True,
            ),
            sa.Column(
                "ip_address",
                sa.String(length=64),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                TIMESTAMP,
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                TIMESTAMP,
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_user_sessions_user_id_users",
                ondelete="CASCADE",
            ),
        )

        op.create_index(
            "ix_user_sessions_id",
            "user_sessions",
            ["id"],
        )

        op.create_index(
            "ix_user_sessions_user_id",
            "user_sessions",
            ["user_id"],
        )

        op.create_index(
            "ix_user_sessions_token_hash",
            "user_sessions",
            ["token_hash"],
            unique=True,
        )

    # ---------------------------------------------------------
    # Password reset tokens
    # ---------------------------------------------------------

    if not _table_exists(
        bind,
        "password_reset_tokens",
    ):
        op.create_table(
            "password_reset_tokens",
            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                nullable=False,
            ),
            sa.Column(
                "token_hash",
                sa.String(length=128),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                TIMESTAMP,
                nullable=False,
            ),
            sa.Column(
                "used_at",
                TIMESTAMP,
                nullable=True,
            ),
            sa.Column(
                "created_at",
                TIMESTAMP, nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                TIMESTAMP,
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_password_reset_tokens_user_id_users",
                ondelete="CASCADE",
            ),
        )

        op.create_index(
            "ix_password_reset_tokens_id",
            "password_reset_tokens",
            ["id"],
        )

        op.create_index(
            "ix_password_reset_tokens_user_id",
            "password_reset_tokens",
            ["user_id"],
        )

        op.create_index(
            "ix_password_reset_tokens_token_hash",
            "password_reset_tokens",
            ["token_hash"],
            unique=True,
        )


def _upgrade_member_status_constraint(bind) -> None:
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_members_valid_status",
            "members",
            type_="check",
        )

        op.create_check_constraint(
            "ck_members_valid_status",
            "members",
            (
                "status IN "
                "('Active', 'Expired', "
                "'Frozen', 'Cancelled')"
            ),
        )

    else:
        with op.batch_alter_table(
            "members",
            recreate="always",
        ) as batch_op:

            batch_op.drop_constraint(
                "ck_members_valid_status",
                type_="check",
            )

            batch_op.create_check_constraint(
                "ck_members_valid_status",
                (
                    "status IN "
                    "('Active', 'Expired', "
                    "'Frozen', 'Cancelled')"
                ),
            )


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(
        bind,
        "gyms",
    ):
        raise RuntimeError(
            "Migration aborted: the gyms table does not exist."
        )

    if bind.dialect.name == "sqlite":
        bind.execute(
            sa.text(
                "PRAGMA foreign_keys=OFF"
            )
        )

    try:
        _upgrade_users_table(bind)
        _create_auth_tables(bind)
        _upgrade_member_status_constraint(bind)

    finally:
        if bind.dialect.name == "sqlite":
            bind.execute(
                sa.text(
                    "PRAGMA foreign_keys=ON"
                )
            )


def downgrade() -> None:
    raise NotImplementedError(
        "0003_align_authentication_schema is intentionally "
        "irreversible because it changes the legacy "
        "authentication schema while preserving existing "
        "account data."
    )
