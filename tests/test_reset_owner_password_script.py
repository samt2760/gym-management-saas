from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest

from app.core.database import SessionLocal
from app.models import AuditLog, Gym
from app.models.user import User, UserSession, hash_password, verify_password
from scripts import reset_owner_password

STRONG_PASSWORD = "NewStrongPass!456"


def _set_args(monkeypatch, gym_id: int, username: str = "owner") -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reset_owner_password.py",
            "--confirm",
            "RESET_OWNER_PASSWORD",
            "--gym-id",
            str(gym_id),
            "--username",
            username,
        ],
    )


def _create_gym(db, name: str) -> Gym:
    gym = Gym(name=name, currency="GHS", registration_fee=200, monthly_fee=120)
    db.add(gym)
    db.commit()
    return gym


def _create_user(
    db,
    gym: Gym,
    *,
    username: str = "owner",
    role: str = "OWNER",
    status: str = "active",
) -> User:
    user = User(
        gym_id=gym.id,
        username=username,
        email=f"{gym.id}-{username}@example.test",
        password_hash=hash_password("ExistingStrongPass!123"),
        role=role,
        status=status,
    )
    db.add(user)
    db.commit()
    return user


def _supply_passwords(monkeypatch, password: str = STRONG_PASSWORD) -> None:
    passwords = iter((password, password))
    monkeypatch.setattr(
        reset_owner_password.getpass, "getpass", lambda _: next(passwords)
    )


def _operator_session(monkeypatch):
    session = SessionLocal()
    monkeypatch.setattr(reset_owner_password, "SessionLocal", lambda: session)


def test_reset_owner_password_requires_explicit_confirmation(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reset_owner_password.py",
            "--confirm",
            "no",
            "--gym-id",
            "1",
            "--username",
            "owner",
        ],
    )

    assert reset_owner_password.main() == 2
    assert "explicit confirmation" in capsys.readouterr().err


@pytest.mark.parametrize("password", ["", "short"])
def test_reset_owner_password_rejects_passwords_that_fail_policy(
    monkeypatch, capsys, password
):
    _set_args(monkeypatch, gym_id=1)
    _supply_passwords(monkeypatch, password)
    monkeypatch.setattr(
        reset_owner_password,
        "SessionLocal",
        lambda: pytest.fail("database must not be opened for a weak password"),
    )

    assert reset_owner_password.main() == 2
    assert "at least" in capsys.readouterr().err


def test_reset_owner_password_refuses_missing_target_gym(monkeypatch, capsys, db):
    _set_args(monkeypatch, gym_id=404)
    _supply_passwords(monkeypatch)
    _operator_session(monkeypatch)

    assert reset_owner_password.main() == 1
    assert "target gym was not found" in capsys.readouterr().err


def test_reset_owner_password_refuses_owner_from_another_gym(monkeypatch, capsys, db):
    owner_gym = _create_gym(db, "Owner Gym")
    target_gym = _create_gym(db, "Target Gym")
    owner = _create_user(db, owner_gym)
    previous_hash = owner.password_hash
    _set_args(monkeypatch, gym_id=target_gym.id)
    _supply_passwords(monkeypatch)
    _operator_session(monkeypatch)

    assert reset_owner_password.main() == 1
    owner_after = db.get(User, owner.id)
    assert owner_after is not None
    assert owner_after.password_hash == previous_hash
    assert "owner was not found" in capsys.readouterr().err


def test_reset_owner_password_refuses_nonexistent_owner(monkeypatch, capsys, db):
    gym = _create_gym(db, "Target Gym")
    _set_args(monkeypatch, gym_id=gym.id, username="missing")
    _supply_passwords(monkeypatch)
    _operator_session(monkeypatch)

    assert reset_owner_password.main() == 1
    assert "owner was not found" in capsys.readouterr().err


def test_reset_owner_password_refuses_a_non_owner(monkeypatch, capsys, db):
    gym = _create_gym(db, "Target Gym")
    _create_user(db, gym, role="MANAGER")
    _set_args(monkeypatch, gym_id=gym.id)
    _supply_passwords(monkeypatch)
    _operator_session(monkeypatch)

    assert reset_owner_password.main() == 1
    assert "not an owner" in capsys.readouterr().err


def test_reset_owner_password_refuses_an_inactive_owner(monkeypatch, capsys, db):
    gym = _create_gym(db, "Target Gym")
    _create_user(db, gym, status="inactive")
    _set_args(monkeypatch, gym_id=gym.id)
    _supply_passwords(monkeypatch)
    _operator_session(monkeypatch)

    assert reset_owner_password.main() == 1
    assert "not active" in capsys.readouterr().err


def test_reset_owner_password_updates_only_target_owner_and_audits(
    monkeypatch, capsys, db
):
    gym = _create_gym(db, "Target Gym")
    owner = _create_user(db, gym)
    other = _create_user(db, gym, username="other-owner")
    active_session = UserSession(
        user_id=owner.id,
        token_hash="target-session",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    other_session = UserSession(
        user_id=other.id,
        token_hash="other-session",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add_all((active_session, other_session))
    db.commit()
    other_hash = other.password_hash
    _set_args(monkeypatch, gym_id=gym.id)
    _supply_passwords(monkeypatch)
    _operator_session(monkeypatch)

    assert reset_owner_password.main() == 0
    db.expire_all()
    owner_after = db.get(User, owner.id)
    other_after = db.get(User, other.id)
    active_session_after = db.get(UserSession, active_session.id)
    other_session_after = db.get(UserSession, other_session.id)
    audit = db.query(AuditLog).one()

    assert owner_after is not None
    assert other_after is not None
    assert active_session_after is not None
    assert other_session_after is not None
    assert verify_password(STRONG_PASSWORD, owner_after.password_hash)
    assert other_after.password_hash == other_hash
    assert active_session_after.revoked_at is not None
    assert other_session_after.revoked_at is None
    assert audit.gym_id == gym.id
    assert audit.action == "auth.owner_password_reset"
    assert audit.resource_type == "user"
    assert audit.resource_id == owner.id
    assert audit.details == {"source": "operator_cli"}
    assert "gym_id=" in capsys.readouterr().out
