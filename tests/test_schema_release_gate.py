import pytest

from scripts import postgres_backup, schema_release_gate


def test_release_image_command_replaces_only_the_database_name():
    command = schema_release_gate._release_image_command(
        "gym_rehearsal", "python", "-m", "alembic", "current"
    )

    assert command[:6] == ["docker", "compose", "run", "--rm", "--no-deps", "web"]
    assert "DATABASE_URL" in command[8]
    assert command[-5:] == ["gym_rehearsal", "python", "-m", "alembic", "current"]


def test_revision_parser_requires_exactly_one_revision():
    assert schema_release_gate._revision_from_output("0007_login_throttles\n") == "0007_login_throttles"
    assert schema_release_gate._revision_from_output(
        "0007_login_throttles (head)\n"
    ) == "0007_login_throttles"

    for output in ("", "0006_audit_trail\n0007_login_throttles\n"):
        try:
            schema_release_gate._revision_from_output(output)
        except postgres_backup.RecoveryError:
            pass
        else:
            raise AssertionError("Expected invalid revision output to fail closed")


def test_rehearsal_refuses_live_target_before_restoring(monkeypatch, tmp_path):
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    monkeypatch.setattr(postgres_backup, "_live_database_name", lambda: "gym_management")

    try:
        schema_release_gate._restore_archive(archive, "gym_management")
    except postgres_backup.RecoveryError as error:
        assert "live application database" in str(error)
    else:
        raise AssertionError("The release gate must refuse a live target")


def test_rehearsal_stops_before_migration_for_an_unexpected_start_revision(monkeypatch, tmp_path):
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(schema_release_gate, "_restore_archive", lambda *_: "/tmp/archive.dump")
    monkeypatch.setattr(
        schema_release_gate, "_assert_pre_migration_state",
        lambda *_: (_ for _ in ()).throw(postgres_backup.RecoveryError("wrong revision")),
    )
    monkeypatch.setattr(schema_release_gate.postgres_backup, "_cleanup_container_archive", lambda *_: None)
    monkeypatch.setattr(schema_release_gate.postgres_backup, "_run", lambda command: commands.append(tuple(command)))

    with pytest.raises(postgres_backup.RecoveryError, match="wrong revision"):
        schema_release_gate.rehearse(archive, "gym_rehearsal", "0004", drop=False)

    assert not any("upgrade" in command for command in commands)


def test_rehearsal_stops_when_migration_command_fails(monkeypatch, tmp_path):
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    monkeypatch.setattr(schema_release_gate, "_restore_archive", lambda *_: "/tmp/archive.dump")
    monkeypatch.setattr(schema_release_gate, "_assert_pre_migration_state", lambda *_: {})
    monkeypatch.setattr(schema_release_gate.postgres_backup, "_cleanup_container_archive", lambda *_: None)
    monkeypatch.setattr(
        schema_release_gate.postgres_backup,
        "_run",
        lambda *_: (_ for _ in ()).throw(postgres_backup.RecoveryError("migration failed")),
    )
    post_check = []
    monkeypatch.setattr(schema_release_gate, "_assert_post_migration_state", lambda *_: post_check.append(True))

    with pytest.raises(postgres_backup.RecoveryError, match="migration failed"):
        schema_release_gate.rehearse(archive, "gym_rehearsal", "0004", drop=False)

    assert post_check == []


def test_post_migration_check_fails_when_required_schema_is_missing(monkeypatch):
    responses = iter([
        "\n".join(schema_release_gate.REQUIRED_TABLES - {"audit_logs"}),
    ])
    monkeypatch.setattr(
        schema_release_gate, "_release_image_revision", lambda _: "0007_login_throttles"
    )
    monkeypatch.setattr(schema_release_gate.postgres_backup, "_query_database", lambda *_: next(responses))

    with pytest.raises(postgres_backup.RecoveryError, match="required tables"):
        schema_release_gate._assert_post_migration_state("gym_rehearsal", {})


def test_post_migration_check_rejects_changed_payment_nine(monkeypatch):
    responses = iter([
        "\n".join(schema_release_gate.REQUIRED_TABLES),
        "status\nidempotency_key",
        "ck_payments_valid_status\nuq_login_throttles_key_hash",
        "\n".join([
            "uq_payments_gym_idempotency_key",
            "ix_audit_logs_gym_created_at",
            "ix_login_throttles_last_attempt_at",
        ]),
        "9|1||saas|201|GHS|2026-08-28|Registration",
    ])
    monkeypatch.setattr(schema_release_gate, "_release_image_revision", lambda _: "0007_login_throttles")
    monkeypatch.setattr(schema_release_gate.postgres_backup, "_query_database", lambda *_: next(responses))

    with pytest.raises(postgres_backup.RecoveryError, match="payment 9"):
        schema_release_gate._assert_post_migration_state("gym_rehearsal", {})
