"""Rehearse a PostgreSQL Alembic release against a disposable restored backup.

This helper intentionally has no command that upgrades the configured live
database.  Operators use it before a separately approved migration job.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import postgres_backup

EXPECTED_HEAD = "0007_login_throttles"
REQUIRED_TABLES = {
    "alembic_version", "gyms", "members", "payments", "users",
    "user_sessions", "password_reset_tokens", "audit_logs", "login_throttles",
}
PAYMENT_9_FACTS = "9|1||saas|200|GHS|2026-08-28|Registration"


def _release_image_command(database_name: str, *command: str) -> list[str]:
    """Run a command in Compose's configured release image against one database."""
    return [
        *postgres_backup.COMPOSE,
        "run", "--rm", "--no-deps", "web", "sh", "-ec",
        'DATABASE_URL="${DATABASE_URL%/*}/$1"; shift; exec "$@"',
        "--", database_name, *command,
    ]


def _revision_from_output(output: str) -> str:
    revisions = {
        line.strip().split()[0] for line in output.splitlines()
        if line.strip().startswith("0")
    }
    if len(revisions) != 1:
        raise postgres_backup.RecoveryError(
            "Could not determine a single Alembic revision from the release image."
        )
    return revisions.pop()


def _release_image_revision(database_name: str) -> str:
    result = postgres_backup._run(
        _release_image_command(database_name, "python", "-m", "alembic", "current")
    )
    return _revision_from_output(result.stdout)


def _restore_archive(archive: Path, recovery_database: str) -> str:
    """Restore only to a validated disposable database and return its container path."""
    if not archive.is_file() or archive.suffix != ".dump":
        raise postgres_backup.RecoveryError("A readable .dump backup archive is required.")
    if not postgres_backup.DATABASE_NAME_PATTERN.fullmatch(recovery_database):
        raise postgres_backup.RecoveryError("Recovery database names must be simple PostgreSQL identifiers.")
    if recovery_database == postgres_backup._live_database_name():
        raise postgres_backup.RecoveryError("Refusing to restore over the configured live application database.")

    container_archive = postgres_backup._copy_archive_to_container(
        archive.resolve(), postgres_backup._container_id()
    )
    created = False
    try:
        postgres_backup._run(postgres_backup._compose_exec("pg_restore", "--list", container_archive))
        postgres_backup._run(postgres_backup._database_command(
            'exec createdb -U "$POSTGRES_USER" "$1"', recovery_database
        ))
        created = True
        postgres_backup._run(postgres_backup._database_command(
            'exec pg_restore --exit-on-error --no-owner --no-privileges '
            '-U "$POSTGRES_USER" -d "$1" "$2"', recovery_database
        ) + [container_archive])
    except Exception:
        postgres_backup._cleanup_container_archive(container_archive)
        if created:
            postgres_backup._run(postgres_backup._database_command(
                'exec dropdb -U "$POSTGRES_USER" "$1"', recovery_database
            ))
        raise
    return container_archive


def _assert_pre_migration_state(database_name: str, expected_start: str) -> dict[str, int]:
    revision = postgres_backup._query_database(
        database_name, "SELECT version_num FROM alembic_version;"
    )
    if revision != expected_start:
        raise postgres_backup.RecoveryError(
            f"Expected restored revision {expected_start}, found {revision or 'none'}."
        )
    postgres_backup._verify_documented_legacy_unlinked_payments(
        postgres_backup._query_database(database_name, postgres_backup.LEGACY_UNLINKED_PAYMENTS_QUERY)
    )
    return postgres_backup._parse_checks(
        postgres_backup._query_database(database_name, postgres_backup.TABLE_COUNT_QUERY)
    )


def _assert_post_migration_state(database_name: str, before: dict[str, int]) -> None:
    revision = _release_image_revision(database_name)
    if revision != EXPECTED_HEAD:
        raise postgres_backup.RecoveryError(
            f"Migration did not reach {EXPECTED_HEAD}; found {revision}."
        )
    tables = set(postgres_backup._query_database(database_name, """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' ORDER BY table_name;
    """).splitlines())
    if not REQUIRED_TABLES <= tables:
        raise postgres_backup.RecoveryError("Migrated database is missing required tables.")
    payment_columns = set(postgres_backup._query_database(database_name, """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'payments';
    """).splitlines())
    if not {"status", "idempotency_key"} <= payment_columns:
        raise postgres_backup.RecoveryError("Migrated payments table is missing required columns.")
    constraints = set(postgres_backup._query_database(database_name, """
        SELECT conname FROM pg_constraint
        WHERE conrelid IN ('payments'::regclass, 'login_throttles'::regclass);
    """).splitlines())
    if not {"ck_payments_valid_status", "uq_login_throttles_key_hash"} <= constraints:
        raise postgres_backup.RecoveryError("Migrated database is missing required constraints.")
    indexes = set(postgres_backup._query_database(database_name, """
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename IN ('payments', 'audit_logs', 'login_throttles');
    """).splitlines())
    required_indexes = {
        "uq_payments_gym_idempotency_key",
        "ix_audit_logs_gym_created_at",
        "ix_login_throttles_last_attempt_at",
    }
    if not required_indexes <= indexes:
        raise postgres_backup.RecoveryError("Migrated database is missing required indexes.")
    payment = postgres_backup._query_database(database_name, """
        SELECT id, gym_id, member_id, member_name, amount, currency, payment_date, payment_type
        FROM payments WHERE id = 9;
    """)
    if payment != PAYMENT_9_FACTS:
        raise postgres_backup.RecoveryError("Migration altered documented payment 9 facts.")
    after = postgres_backup._parse_checks(
        postgres_backup._query_database(database_name, postgres_backup.TABLE_COUNT_QUERY)
    )
    for table, count in before.items():
        if after.get(table) != count:
            raise postgres_backup.RecoveryError(
                f"Migration changed preserved row count for {table}."
            )
    postgres_backup._verify_documented_legacy_unlinked_payments(
        postgres_backup._query_database(database_name, postgres_backup.LEGACY_UNLINKED_PAYMENTS_QUERY)
    )
    postgres_backup._run(_release_image_command(
        database_name,
        "python", "-c",
        "c=__import__('fastapi.testclient',fromlist=['TestClient']).TestClient;"
        "a=__import__('app.main',fromlist=['app']).app;"
        "c(a).get('/health').raise_for_status()",
    ))


def rehearse(archive: Path, recovery_database: str, expected_start: str, *, drop: bool) -> None:
    """Restore, migrate, validate, and optionally drop one disposable database."""
    container_archive: str | None = None
    created = False
    try:
        container_archive = _restore_archive(archive, recovery_database)
        created = True
        before = _assert_pre_migration_state(recovery_database, expected_start)
        postgres_backup._run(_release_image_command(
            recovery_database, "python", "-m", "alembic", "upgrade", "head"
        ))
        _assert_post_migration_state(recovery_database, before)
    finally:
        if container_archive:
            postgres_backup._cleanup_container_archive(container_archive)
        if created and drop:
            postgres_backup._run(postgres_backup._database_command(
                'exec dropdb -U "$POSTGRES_USER" "$1"', recovery_database
            ))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--recovery-database", required=True)
    parser.add_argument("--expected-start", required=True)
    parser.add_argument("--drop-recovery-database", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rehearse(args.archive, args.recovery_database, args.expected_start,
                 drop=args.drop_recovery_database)
        print(f"Migration rehearsal passed: {EXPECTED_HEAD}")
        return 0
    except postgres_backup.RecoveryError as error:
        print(f"Migration rehearsal failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
