"""Tests for the safe PostgreSQL backup/recovery helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import postgres_backup


def test_backup_artifacts_are_ignored_by_git():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "*.dump" in gitignore
    assert "backups/" in gitignore


def test_recovery_target_must_be_a_safe_explicit_identifier(tmp_path):
    archive = tmp_path / "recovery.dump"
    archive.write_bytes(b"archive")

    with pytest.raises(postgres_backup.RecoveryError, match="identifiers"):
        postgres_backup.verify_restore(
            archive,
            "gym; DROP DATABASE gym_management",
            drop_recovery_database=True,
        )


def test_recovery_refuses_the_live_database(monkeypatch, tmp_path):
    archive = tmp_path / "recovery.dump"
    archive.write_bytes(b"archive")
    monkeypatch.setattr(
        postgres_backup, "_live_database_name", lambda: "gym_management")

    with pytest.raises(postgres_backup.RecoveryError, match="live application database"):
        postgres_backup.verify_restore(
            archive,
            "gym_management",
            drop_recovery_database=True,
        )


def test_integrity_queries_cover_recovered_operational_records():
    expected_tables = {
        "alembic_version",
        "gyms",
        "users",
        "members",
        "payments",
        "user_sessions",
        "password_reset_tokens",
    }
    query_text = postgres_backup.TABLE_COUNT_QUERY + postgres_backup.INTEGRITY_QUERY

    for table in expected_tables:
        assert table in query_text
    assert "orphan_members" in postgres_backup.INTEGRITY_QUERY
    assert "orphan_payments_members" in postgres_backup.INTEGRITY_QUERY
    assert "orphan_sessions" in postgres_backup.INTEGRITY_QUERY
    assert "reset_tokens_without_user" in postgres_backup.INTEGRITY_QUERY
    assert "LEFT JOIN members" in postgres_backup.INTEGRITY_QUERY
    assert "LEFT JOIN users" in postgres_backup.INTEGRITY_QUERY
    assert "p.member_id IS NOT NULL" in postgres_backup.INTEGRITY_QUERY


def test_only_the_exact_documented_legacy_unlinked_payment_is_allowed():
    expected = "|".join(postgres_backup.DOCUMENTED_LEGACY_UNLINKED_PAYMENT)

    postgres_backup._verify_documented_legacy_unlinked_payments(expected)
    postgres_backup._verify_documented_legacy_unlinked_payments("")

    with pytest.raises(postgres_backup.RecoveryError, match="undocumented"):
        postgres_backup._verify_documented_legacy_unlinked_payments(
            expected.replace("|200|", "|201|", 1)
        )

    with pytest.raises(postgres_backup.RecoveryError, match="undocumented"):
        postgres_backup._verify_documented_legacy_unlinked_payments(
            f"{expected}\n10|1|other|200|GHS|2026-08-28|Monthly|Registration"
        )


def test_backup_refuses_to_overwrite_existing_archive(tmp_path):
    archive = tmp_path / "existing.dump"
    archive.write_bytes(b"existing")

    with pytest.raises(postgres_backup.RecoveryError, match="overwrite"):
        postgres_backup.create_backup(archive)
