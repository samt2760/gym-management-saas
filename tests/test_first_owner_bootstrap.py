"""Focused coverage for the one-shot first-owner bootstrap service."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.models.gym import Gym
from app.models.user import User, verify_password
from app.services import bootstrap_service
from app.services.bootstrap_service import (
    BootstrapAlreadyInitializedError,
    BootstrapError,
    BootstrapPrivilegeError,
    FirstOwnerBootstrap,
    bootstrap_first_owner,
)


def _request(**overrides) -> FirstOwnerBootstrap:
    values = {
        "gym_name": "Bootstrap Gym",
        "currency": "ghs",
        "registration_fee": 25,
        "monthly_fee": 120,
        "username": "first-owner",
        "email": "owner@example.test",
        "password": "StrongPass!123",
    }
    values.update(overrides)
    return FirstOwnerBootstrap(**values)


def test_fresh_bootstrap_creates_login_capable_owner(db):
    result = bootstrap_first_owner(db, _request())

    gym = db.get(Gym, result.gym_id)
    owner = db.get(User, result.owner_id)
    assert gym is not None
    assert gym.name == "Bootstrap Gym"
    assert gym.currency == "GHS"
    assert owner is not None
    assert owner.gym_id == gym.id
    assert owner.role == "OWNER"
    assert owner.is_superuser is True
    assert owner.password_hash != "StrongPass!123"
    assert verify_password("StrongPass!123", owner.password_hash)

    from app.main import app

    with TestClient(app, base_url="https://testserver") as client:
        client.get("/login")
        response = client.post(
            "/login",
            data={
                "username": "first-owner",
                "password": "StrongPass!123",
                "csrf_token": client.cookies["csrf_token"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"
        assert client.get("/dashboard").status_code == 200


def test_second_bootstrap_refuses_without_creating_additional_records(db):
    bootstrap_first_owner(db, _request())

    with pytest.raises(BootstrapAlreadyInitializedError):
        bootstrap_first_owner(db, _request(username="another-owner"))

    assert db.query(Gym).count() == 1
    assert db.query(User).count() == 1


@pytest.mark.parametrize(
    "bootstrap_request",
    [
        _request(gym_name=" "),
        _request(currency="GH"),
        _request(email="not-an-email"),
        _request(registration_fee=-1),
        _request(password="short"),
    ],
)
def test_invalid_input_is_refused_without_persistence(db, bootstrap_request):
    with pytest.raises(BootstrapError):
        bootstrap_first_owner(db, bootstrap_request)

    assert db.query(Gym).count() == 0
    assert db.query(User).count() == 0


def test_failure_after_gym_flush_rolls_back_everything(db, monkeypatch):
    def fail_hash(_password: str) -> str:
        raise RuntimeError("controlled password-hash failure")

    monkeypatch.setattr(bootstrap_service, "hash_password", fail_hash)

    with pytest.raises(RuntimeError, match="controlled password-hash failure"):
        bootstrap_first_owner(db, _request())

    assert db.query(Gym).count() == 0
    assert db.query(User).count() == 0


def test_postgresql_runtime_role_without_bypassrls_is_refused_before_querying():
    session = MagicMock()
    session.bind.dialect.name = "postgresql"
    session.execute.return_value.scalar_one_or_none.return_value = False

    with pytest.raises(BootstrapPrivilegeError, match="BYPASSRLS"):
        bootstrap_first_owner(session, _request())

    session.query.assert_not_called()
    session.rollback.assert_called_once()
