"""Provider-neutral PostgreSQL logical backup and disposable restore validator.

Credentials are read from environment-only PostgreSQL URLs and translated to
libpq environment variables before invoking native ``pg_dump``, ``pg_restore``
and ``psql``.  URLs are never placed in child-process arguments or output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXPECTED_TABLES = {
    "gyms",
    "members",
    "payments",
    "audit_logs",
    "legacy_member_records",
}
RLS_TABLES = ("gyms", "members", "payments", "audit_logs", "legacy_member_records")


class ArchiveError(RuntimeError):
    """Raised for a safe backup, restore, or verification refusal."""


@dataclass(frozen=True)
class ConnectionInfo:
    host: str
    port: str
    user: str
    database: str
    password: str | None
    options: dict[str, str]


@dataclass(frozen=True)
class ArchiveMetadata:
    created_at_utc: str
    source_fingerprint: str
    source_database: str
    alembic_revision: str | None
    archive_size_bytes: int
    sha256: str


def _connection_info(url: str) -> ConnectionInfo:
    normalized = url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
        raise ArchiveError("A PostgreSQL connection URL is required.")
    database = parsed.path.lstrip("/")
    if not database or not SAFE_DATABASE_NAME.fullmatch(database):
        raise ArchiveError("Connection URL must name a safe PostgreSQL database.")
    query = parse_qs(parsed.query, keep_blank_values=False)
    options = {key: values[-1] for key, values in query.items() if values}
    return ConnectionInfo(
        host=parsed.hostname,
        port=str(parsed.port or 5432),
        user=unquote(parsed.username or ""),
        database=database,
        password=unquote(parsed.password) if parsed.password is not None else None,
        options=options,
    )


def _libpq_environment(
    info: ConnectionInfo, *, database: str | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": info.host,
            "PGPORT": info.port,
            "PGUSER": info.user,
            "PGDATABASE": database or info.database,
        }
    )
    if info.password is not None:
        environment["PGPASSWORD"] = info.password
    for option, value in info.options.items():
        key = f"PG{option.upper()}"
        if key in {"PGSSLMODE", "PGSSLROOTCERT", "PGSSLCERT", "PGSSLKEY"}:
            environment[key] = value
    return environment


def _run(
    command: list[str], environment: dict[str, str], *, input_text: str | None = None
) -> str:
    result = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    if result.returncode:
        raise ArchiveError(
            "PostgreSQL archive operation failed; inspect secure operator logs."
        )
    return result.stdout


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as archive:
        for block in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _revision(info: ConnectionInfo) -> str | None:
    try:
        revision = _run(
            [
                "psql",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT version_num FROM alembic_version",
            ],
            _libpq_environment(info),
        ).strip()
    except ArchiveError:
        return None
    return revision or None


def _archive_path(path: Path) -> Path:
    archive = path.expanduser().resolve()
    if archive.suffix != ".dump":
        raise ArchiveError("Archives must use the .dump extension.")
    if archive.exists() or archive.with_suffix(".dump.partial").exists():
        raise ArchiveError(
            "Refusing to overwrite an existing archive or partial archive."
        )
    archive.parent.mkdir(parents=True, exist_ok=True)
    return archive


def create_backup(source_url: str, output: Path) -> tuple[Path, ArchiveMetadata]:
    """Create an atomic custom-format dump without credential command arguments."""

    source = _connection_info(source_url)
    archive = _archive_path(output)
    partial = archive.with_suffix(".dump.partial")
    try:
        _run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(partial),
            ],
            _libpq_environment(source),
        )
        if not partial.is_file() or partial.stat().st_size == 0:
            raise ArchiveError("pg_dump did not produce a complete archive.")
        partial.replace(archive)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    source_id = f"{source.host}:{source.port}/{source.database}"
    metadata = ArchiveMetadata(
        created_at_utc=datetime.now(UTC).isoformat(),
        source_fingerprint=hashlib.sha256(source_id.encode()).hexdigest(),
        source_database=source.database,
        alembic_revision=_revision(source),
        archive_size_bytes=archive.stat().st_size,
        sha256=_checksum(archive),
    )
    archive.with_suffix(".dump.json").write_text(
        json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return archive, metadata


def verify_archive(archive: Path) -> ArchiveMetadata:
    """Check checksum and required application objects without restoring."""

    archive = archive.expanduser().resolve()
    metadata_path = archive.with_suffix(".dump.json")
    if not archive.is_file() or not metadata_path.is_file():
        raise ArchiveError("Archive and adjacent metadata file are required.")
    try:
        metadata = ArchiveMetadata(
            **json.loads(metadata_path.read_text(encoding="utf-8"))
        )
    except (OSError, TypeError, json.JSONDecodeError) as error:
        raise ArchiveError("Archive metadata is unreadable.") from error
    if metadata.sha256 != _checksum(archive):
        raise ArchiveError("Archive checksum does not match its metadata.")
    listing = _run(["pg_restore", "--list", str(archive)], os.environ.copy())
    missing = {table for table in EXPECTED_TABLES if table not in listing}
    if missing:
        raise ArchiveError("Archive is missing required application tables.")
    return metadata


def _query(info: ConnectionInfo, query: str) -> str:
    return _run(
        ["psql", "-At", "-v", "ON_ERROR_STOP=1", "-F", "|", "-c", query],
        _libpq_environment(info),
    ).strip()


def restore_and_validate(
    archive: Path,
    recovery_admin_url: str,
    recovery_database: str,
    *,
    drop_recovery_database: bool,
) -> str:
    """Restore only to a named fresh database and verify schema/RLS invariants."""

    verify_archive(archive)
    admin = _connection_info(recovery_admin_url)
    if not SAFE_DATABASE_NAME.fullmatch(recovery_database):
        raise ArchiveError("Recovery database name must be a simple identifier.")
    if recovery_database == admin.database:
        raise ArchiveError(
            "Recovery target must differ from the admin/source database."
        )
    created = False
    try:
        _run(["createdb", recovery_database], _libpq_environment(admin))
        created = True
        _run(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                recovery_database,
                str(archive),
            ],
            _libpq_environment(admin),
        )
        restored = ConnectionInfo(
            host=admin.host,
            port=admin.port,
            user=admin.user,
            database=recovery_database,
            password=admin.password,
            options=admin.options,
        )
        revision = _query(restored, "SELECT version_num FROM alembic_version")
        if not revision:
            raise ArchiveError("Restored database has no Alembic revision.")
        protected = _query(
            restored,
            "SELECT tablename || '|' || rowsecurity || '|' || forcerowsecurity "
            "FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename IN ('gyms','members','payments','audit_logs','legacy_member_records')",
        ).splitlines()
        expected = {f"{table}|t|t" for table in RLS_TABLES}
        if set(protected) != expected:
            raise ArchiveError(
                "Restored database does not preserve enabled forced RLS."
            )
        policies = _query(
            restored,
            "SELECT tablename FROM pg_policies WHERE schemaname = 'public' "
            "AND policyname = 'tenant_gym_isolation'",
        ).splitlines()
        if set(policies) != set(RLS_TABLES):
            raise ArchiveError(
                "Restored database does not preserve tenant RLS policies."
            )
        return revision
    finally:
        if created and drop_recovery_database:
            _run(["dropdb", recovery_database], _libpq_environment(admin))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True, type=Path)
    restore = commands.add_parser("restore-validate")
    restore.add_argument("--archive", required=True, type=Path)
    restore.add_argument("--recovery-database", required=True)
    restore.add_argument("--drop-recovery-database", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "backup":
            archive, metadata = create_backup(
                os.environ["BACKUP_DATABASE_URL"], args.output
            )
            print(
                f"Backup created: {archive.name} ({metadata.archive_size_bytes} bytes)"
            )
        elif args.command == "verify":
            metadata = verify_archive(args.archive)
            print(f"Archive verified: {metadata.archive_size_bytes} bytes")
        else:
            revision = restore_and_validate(
                args.archive,
                os.environ["RECOVERY_ADMIN_DATABASE_URL"],
                args.recovery_database,
                drop_recovery_database=args.drop_recovery_database,
            )
            print(f"Restore validation passed: {revision}")
        return 0
    except (ArchiveError, KeyError):
        print(
            "Archive operation failed; inspect secure operator logs.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
