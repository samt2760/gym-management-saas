"""Unit coverage for provider-neutral native PostgreSQL archive operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import postgres_archive


def test_connection_urls_are_converted_to_libpq_environment_without_command_credentials():
    info = postgres_archive._connection_info(
        "postgresql+psycopg://backup_user:secret-value@db.example.test:5444/gym?sslmode=verify-full"
    )
    environment = postgres_archive._libpq_environment(info)

    assert environment["PGHOST"] == "db.example.test"
    assert environment["PGPASSWORD"] == "secret-value"
    command = "pg_dump --format=custom"
    assert "secret-value" not in command


@pytest.mark.parametrize("url", ["", "sqlite:///gym.db", "postgresql://user@host/"])
def test_invalid_connection_url_is_refused(url):
    with pytest.raises(postgres_archive.ArchiveError):
        postgres_archive._connection_info(url)


def test_backup_is_atomic_and_writes_checksum_metadata(monkeypatch, tmp_path):
    def fake_run(command, _environment, **_kwargs):
        if command[0] == "psql":
            return "0009_postgresql_tenant_rls\n"
        output = Path(command[command.index("--file") + 1])
        output.write_bytes(b"archive")
        return ""

    monkeypatch.setattr(postgres_archive, "_run", fake_run)
    archive, metadata = postgres_archive.create_backup(
        "postgresql://backup:secret@db.test/gym", tmp_path / "gym.dump"
    )

    assert archive.is_file()
    assert metadata.alembic_revision == "0009_postgresql_tenant_rls"
    assert metadata.sha256 == postgres_archive._checksum(archive)
    assert "secret" not in archive.with_suffix(".dump.json").read_text()


def test_backup_failure_removes_partial_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(
        postgres_archive,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            postgres_archive.ArchiveError("failed")
        ),
    )
    with pytest.raises(postgres_archive.ArchiveError):
        postgres_archive.create_backup(
            "postgresql://backup@db.test/gym", tmp_path / "gym.dump"
        )
    assert not (tmp_path / "gym.dump.partial").exists()


def test_verify_rejects_checksum_mismatch(monkeypatch, tmp_path):
    archive = tmp_path / "gym.dump"
    archive.write_bytes(b"archive")
    archive.with_suffix(".dump.json").write_text(
        '{"created_at_utc":"x","source_fingerprint":"x","source_database":"gym","alembic_revision":null,"archive_size_bytes":7,"sha256":"wrong"}'
    )
    with pytest.raises(postgres_archive.ArchiveError, match="checksum"):
        postgres_archive.verify_archive(archive)


def test_restore_refuses_unsafe_target_name(tmp_path):
    archive = tmp_path / "gym.dump"
    archive.write_bytes(b"archive")
    archive.with_suffix(".dump.json").write_text("{}")
    with pytest.raises(postgres_archive.ArchiveError, match="metadata"):
        postgres_archive.restore_and_validate(
            archive,
            "postgresql://backup@db.test/admin",
            "bad;drop database",
            drop_recovery_database=True,
        )
