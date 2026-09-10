"""Create and verify safe PostgreSQL backups using the Compose database service.

The helper intentionally never accepts a live restore target.  It uses the
database service's POSTGRES_USER and POSTGRES_DB environment variables, so
credentials are neither embedded in commands nor written to backup files.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

COMPOSE = ("docker", "compose")
DATABASE_SERVICE = "db"
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RecoveryError(RuntimeError):
    """Raised when a backup or disposable recovery verification fails."""


def _run(command: list[str], *, input_stream=None, text: bool = True) -> subprocess.CompletedProcess:
    """Run Docker without echoing commands or database output to the console."""
    result = subprocess.run(
        command,
        stdin=input_stream,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        check=False,
    )
    if result.returncode:
        raise RecoveryError(
            "PostgreSQL backup or recovery command failed; inspect Docker logs.")
    return result


def _compose_exec(*command: str) -> list[str]:
    return [*COMPOSE, "exec", "-T", DATABASE_SERVICE, *command]


def _live_database_name() -> str:
    result = _run(_compose_exec("printenv", "POSTGRES_DB"))
    database_name = result.stdout.strip()
    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise RecoveryError(
            "The configured PostgreSQL database name is invalid.")
    return database_name


def _container_id() -> str:
    result = _run([*COMPOSE, "ps", "-q", DATABASE_SERVICE])
    container_id = result.stdout.strip()
    if not container_id:
        raise RecoveryError("The PostgreSQL Compose service is not running.")
    return container_id


def _ensure_archive_path(archive: Path) -> Path:
    archive = archive.expanduser().resolve()
    if archive.suffix != ".dump":
        raise RecoveryError("Backup archives must use the .dump extension.")
    if archive.exists():
        raise RecoveryError(
            "Refusing to overwrite an existing backup archive.")
    archive.parent.mkdir(parents=True, exist_ok=True)
    return archive


def create_backup(archive: Path) -> Path:
    """Create an atomic custom-format archive from the live Compose database."""
    archive = _ensure_archive_path(archive)
    partial = archive.with_suffix(".dump.partial")
    if partial.exists():
        raise RecoveryError(
            "A partial backup archive already exists; inspect it before retrying.")

    command = _compose_exec(
        "sh",
        "-ec",
        'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        "--format=custom --no-owner --no-privileges",
    )
    try:
        with partial.open("xb") as output:
            result = subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.PIPE,
                text=False,
                check=False,
            )
        if result.returncode:
            raise RecoveryError(
                "pg_dump failed; no backup archive was created.")
        if partial.stat().st_size == 0:
            raise RecoveryError("pg_dump created an empty backup archive.")
        partial.replace(archive)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return archive


def _copy_archive_to_container(archive: Path, container_id: str) -> str:
    container_archive = f"/tmp/gym-recovery-{uuid.uuid4().hex}.dump"
    _run(["docker", "cp", str(archive), f"{container_id}:{container_archive}"])
    return container_archive


def _cleanup_container_archive(container_archive: str) -> None:
    subprocess.run(
        _compose_exec("rm", "-f", "--", container_archive),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _database_command(command: str, database_name: str) -> list[str]:
    return _compose_exec("sh", "-ec", command, "--", database_name)


def _query_database(database_name: str, query: str) -> str:
    result = _run(
        _database_command(
            'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -At -F "|" -c "$2"',
            database_name,
        )
        + [query]
    )
    return result.stdout.strip()


TABLE_COUNT_QUERY = """
SELECT 'alembic_version', COUNT(*) FROM alembic_version
UNION ALL SELECT 'gyms', COUNT(*) FROM gyms
UNION ALL SELECT 'members', COUNT(*) FROM members
UNION ALL SELECT 'payments', COUNT(*) FROM payments
UNION ALL SELECT 'users', COUNT(*) FROM users
UNION ALL SELECT 'user_sessions', COUNT(*) FROM user_sessions
UNION ALL SELECT 'password_reset_tokens', COUNT(*) FROM password_reset_tokens
ORDER BY 1;
"""
INTEGRITY_QUERY = """
SELECT 'orphan_members', COUNT(*)
FROM members m
LEFT JOIN gyms g ON g.id = m.gym_id
WHERE g.id IS NULL

UNION ALL

SELECT 'orphan_payments_members', COUNT(*)
FROM payments p
LEFT JOIN members m ON m.id = p.member_id
WHERE p.member_id IS NOT NULL AND m.id IS NULL

UNION ALL

SELECT 'orphan_sessions', COUNT(*)
FROM user_sessions s
LEFT JOIN users u ON u.id = s.user_id
WHERE u.id IS NULL

UNION ALL

SELECT 'reset_tokens_without_user', COUNT(*)
FROM password_reset_tokens t
LEFT JOIN users u ON u.id = t.user_id
WHERE u.id IS NULL

ORDER BY 1;
"""

# This row predates member linkage enforcement.  It is retained verbatim for
# accounting history until the reviewed archived-legacy-member migration is
# deployed.  This is deliberately an exact, finite allow-list rather than a
# general allowance for unlinked payments: any other NULL member_id fails a
# recovery verification.
DOCUMENTED_LEGACY_UNLINKED_PAYMENT = (
    "9", "1", "saas", "200", "GHS", "2026-08-28", "Monthly", "Registration",
)
LEGACY_UNLINKED_PAYMENTS_QUERY = """
SELECT id, gym_id, member_name, amount, currency, payment_date,
       membership_type, payment_type
FROM payments
WHERE member_id IS NULL
ORDER BY id;
"""


def _parse_checks(output: str) -> dict[str, int]:
    checks: dict[str, int] = {}
    for line in output.splitlines():
        name, separator, value = line.partition("|")
        if not separator or not value.isdigit():
            raise RecoveryError(
                "Recovery verification returned an unexpected result.")
        checks[name] = int(value)
    return checks


def _verify_documented_legacy_unlinked_payments(output: str) -> None:
    """Permit only the explicitly documented pre-linkage ledger row."""
    rows = [tuple(line.split("|")) for line in output.splitlines() if line]
    if not rows:
        return
    if rows != [DOCUMENTED_LEGACY_UNLINKED_PAYMENT]:
        raise RecoveryError(
            "Recovered database contains an undocumented unlinked payment."
        )


def verify_restore(
    archive: Path,
    recovery_database: str,
    *,
    drop_recovery_database: bool,
) -> tuple[dict[str, int], str]:
    """Restore an archive to a separate database and verify its integrity."""
    archive = archive.expanduser().resolve()
    if not archive.is_file() or archive.suffix != ".dump":
        raise RecoveryError("A readable .dump backup archive is required.")
    if not DATABASE_NAME_PATTERN.fullmatch(recovery_database):
        raise RecoveryError(
            "Recovery database names must be simple PostgreSQL identifiers.")
    if recovery_database == _live_database_name():
        raise RecoveryError(
            "Refusing to restore over the configured live application database.")

    container_id = _container_id()
    container_archive = _copy_archive_to_container(archive, container_id)
    created = False
    try:
        _run(_compose_exec("pg_restore", "--list", container_archive))
        _run(
            _database_command(
                'exec createdb -U "$POSTGRES_USER" "$1"', recovery_database
            )
        )
        created = True
        _run(
            _database_command(
                'exec pg_restore --exit-on-error --no-owner --no-privileges '
                '-U "$POSTGRES_USER" -d "$1" "$2"',
                recovery_database,
            )
            + [container_archive]
        )
        counts = _parse_checks(_query_database(
            recovery_database, TABLE_COUNT_QUERY))
        integrity = _parse_checks(_query_database(
            recovery_database, INTEGRITY_QUERY))
        _verify_documented_legacy_unlinked_payments(_query_database(
            recovery_database, LEGACY_UNLINKED_PAYMENTS_QUERY))
        invalid = {name: count for name, count in integrity.items() if count}
        if invalid:
            raise RecoveryError(
                "Recovered database failed orphan or structural integrity checks.")
        revision = _query_database(
            recovery_database, "SELECT version_num FROM alembic_version;")
        if not revision:
            raise RecoveryError("Recovered database has no Alembic revision.")
        return counts, revision
    finally:
        _cleanup_container_archive(container_archive)
        if created and drop_recovery_database:
            _run(
                _database_command(
                    'exec dropdb -U "$POSTGRES_USER" "$1"', recovery_database
                )
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser(
        "backup", help="Create a PostgreSQL custom archive.")
    backup.add_argument("--output", required=True, type=Path)

    verify = commands.add_parser(
        "verify-restore", help="Restore an archive only into a disposable database."
    )
    verify.add_argument("--archive", required=True, type=Path)
    verify.add_argument("--recovery-database", required=True)
    verify.add_argument("--drop-recovery-database", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "backup":
            archive = create_backup(args.output)
            print(f"Backup created: {archive}")
            return 0
        counts, revision = verify_restore(
            args.archive,
            args.recovery_database,
            drop_recovery_database=args.drop_recovery_database,
        )
        print("Recovery verification passed.")
        print("Table counts:", ", ".join(
            f"{name}={count}" for name, count in counts.items()))
        print(f"Alembic revision: {revision}")
        return 0
    except RecoveryError as error:
        print(f"Recovery verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
