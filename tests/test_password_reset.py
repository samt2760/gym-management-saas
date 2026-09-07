from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import (
    _unknown_reset_attempts,
    create_password_reset_token,
    is_password_reset_allowed,
)
from app.main import app
from app.models import Gym
from app.models.user import PasswordResetToken, User, UserSession, hash_password
from app.services.password_reset_delivery import development_delivery


PASSWORD = "StrongPass!123"


def _create_user(db, username: str = "admin") -> User:
    gym = db.query(Gym).filter(Gym.id == 1).first()
    if gym is None:
        gym = Gym(
            name="Reset Test Gym",
            currency="GHS",
            registration_fee=200,
            monthly_fee=120,
        )
        db.add(gym)
        db.flush()

    user = User(
        username=username,
        email=f"{username}@example.test",
        password_hash=hash_password(PASSWORD),
        status="active",
        role="OWNER",
        is_superuser=True,
        gym_id=gym.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _csrf_token(client: TestClient) -> str:
    token = client.cookies.get("csrf_token")
    if token is None:
        response = client.get("/account/password/forgot")
        assert response.status_code == status.HTTP_200_OK
        token = client.cookies.get("csrf_token")
    assert token
    return token


def _request_reset(client: TestClient, email: str):
    return client.post(
        "/account/password/reset-request",
        data={
            "email": email,
            "csrf_token": _csrf_token(client),
        },
    )


def _login(client: TestClient, username: str = "admin"):
    return client.post(
        "/login",
        data={
            "username": username,
            "password": PASSWORD,
            "csrf_token": _csrf_token(client),
        },
        follow_redirects=False,
    )


@pytest.fixture(autouse=True)
def clear_delivery_and_rate_limit():
    development_delivery.clear()
    _unknown_reset_attempts.clear()
    yield
    development_delivery.clear()
    _unknown_reset_attempts.clear()


def test_forgot_page_is_public_and_reset_request_requires_csrf(public_client):
    response = public_client.get("/account/password/forgot")
    assert response.status_code == status.HTTP_200_OK
    assert "Forgot password?" in response.text

    response = public_client.post(
        "/account/password/reset-request",
        data={"email": "admin@example.test"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_existing_and_unknown_reset_requests_have_same_generic_response(
    public_client,
    db,
):
    _create_user(db)
    existing = _request_reset(public_client, " ADMIN@EXAMPLE.TEST ")
    development_delivery.clear()
    unknown = _request_reset(public_client, "missing@example.test")

    assert existing.status_code == status.HTTP_200_OK
    assert unknown.status_code == status.HTTP_200_OK
    assert "If the account exists, a reset link has been sent." in existing.text
    assert existing.text == unknown.text
    assert len(development_delivery.messages) == 0


def test_reset_delivery_contains_raw_token_only_in_controlled_test_sink(
    public_client,
    db,
    caplog,
):
    user = _create_user(db)
    response = _request_reset(public_client, user.email)

    assert response.status_code == status.HTTP_200_OK
    assert len(development_delivery.messages) == 1
    message = development_delivery.messages[0]
    token = parse_qs(urlparse(message.reset_url).query)["token"][0]
    stored = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
    ).one()

    assert message.recipient == user.email
    assert token not in stored.token_hash
    assert token not in response.text
    assert token not in caplog.text


def test_new_reset_request_invalidates_previous_token(public_client, db):
    user = _create_user(db)
    _request_reset(public_client, user.email)
    first_token = parse_qs(
        urlparse(development_delivery.messages[-1].reset_url).query,
    )["token"][0]
    _request_reset(public_client, user.email)
    second_token = parse_qs(
        urlparse(development_delivery.messages[-1].reset_url).query,
    )["token"][0]

    assert first_token != second_token
    response = public_client.post(
        "/account/password/reset",
        data={
            "token": first_token,
            "new_password": "NewStrongPass!456",
            "confirm_password": "NewStrongPass!456",
            "csrf_token": _csrf_token(public_client),
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid or expired reset token." in response.text


def test_reset_validates_password_and_consumes_token(public_client, db):
    user = _create_user(db)
    _request_reset(public_client, user.email)
    token = parse_qs(urlparse(development_delivery.messages[-1].reset_url).query)["token"][0]

    response = public_client.post(
        "/account/password/reset",
        data={
            "token": token,
            "new_password": "short",
            "confirm_password": "short",
            "csrf_token": _csrf_token(public_client),
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    response = public_client.post(
        "/account/password/reset",
        data={
            "token": token,
            "new_password": "NewStrongPass!456",
            "confirm_password": "DifferentStrongPass!789",
            "csrf_token": _csrf_token(public_client),
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    response = public_client.post(
        "/account/password/reset",
        data={
            "token": token,
            "new_password": "NewStrongPass!456",
            "confirm_password": "NewStrongPass!456",
            "csrf_token": _csrf_token(public_client),
        },
    )
    assert response.status_code == status.HTTP_200_OK
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
    ).one()
    assert reset.used_at is not None

    response = public_client.post(
        "/account/password/reset",
        data={
            "token": token,
            "new_password": "AnotherStrongPass!789",
            "confirm_password": "AnotherStrongPass!789",
            "csrf_token": _csrf_token(public_client),
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_reset_submission_requires_csrf(public_client, db):
    user = _create_user(db)
    token = create_password_reset_token(db, user)

    response = public_client.post(
        "/account/password/reset",
        data={
            "token": token,
            "new_password": "NewStrongPass!456",
            "confirm_password": "NewStrongPass!456",
        },
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
    ).one()
    assert reset.used_at is None


def test_expired_reset_token_fails(public_client, db):
    user = _create_user(db)
    token = create_password_reset_token(db, user)
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
    ).one()
    reset.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = public_client.post(
        "/account/password/reset",
        data={
            "token": token,
            "new_password": "NewStrongPass!456",
            "confirm_password": "NewStrongPass!456",
            "csrf_token": _csrf_token(public_client),
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_successful_reset_revokes_only_that_users_sessions(
    public_client,
    db,
):
    user = _create_user(db)
    other = _create_user(db, "other")
    with TestClient(app, base_url="https://testserver") as other_client:
        assert _login(public_client).status_code == status.HTTP_303_SEE_OTHER
        assert _login(other_client, "other").status_code == status.HTTP_303_SEE_OTHER

        _request_reset(public_client, user.email)
        token = parse_qs(
            urlparse(development_delivery.messages[-1].reset_url).query,
        )["token"][0]
        response = public_client.post(
            "/account/password/reset",
            data={
                "token": token,
                "new_password": "NewStrongPass!456",
                "confirm_password": "NewStrongPass!456",
                "csrf_token": _csrf_token(public_client),
            },
        )
        assert response.status_code == status.HTTP_200_OK

        user_session = db.query(UserSession).filter(
            UserSession.user_id == user.id,
        ).one()
        other_session = db.query(UserSession).filter(
            UserSession.user_id == other.id,
        ).one()
        assert user_session.revoked_at is not None
        assert other_session.revoked_at is None

        assert public_client.get("/dashboard", follow_redirects=False).status_code == 307
        assert other_client.get("/dashboard").status_code == 200


def test_reset_request_rate_limit_is_shared_for_existing_accounts(
    public_client,
    db,
    monkeypatch,
):
    user = _create_user(db)
    monkeypatch.setattr("app.auth.PASSWORD_RESET_MAX_REQUESTS", 2)
    monkeypatch.setattr("app.auth.PASSWORD_RESET_RATE_LIMIT_SECONDS", 60)

    assert _request_reset(public_client, user.email).status_code == 200
    assert _request_reset(public_client, user.email).status_code == 200
    assert _request_reset(public_client, user.email).status_code == 200
    assert len(development_delivery.messages) == 2

    tokens = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
    ).all()
    for reset in tokens:
        reset.created_at = datetime.now(UTC) - timedelta(seconds=61)
    db.commit()

    assert _request_reset(public_client, user.email).status_code == 200
    assert len(development_delivery.messages) == 3


def test_unknown_identifier_rate_limit_is_bounded_and_normalized(
    public_client,
    db,
    monkeypatch,
):
    request = Request({"type": "http", "client": ("127.0.0.1", 1234)})
    monkeypatch.setattr("app.auth.PASSWORD_RESET_MAX_REQUESTS", 1)
    for index in range(10050):
        is_password_reset_allowed(db, f" User{index}@Example.test ", request)

    assert len(_unknown_reset_attempts) <= 10000
    assert not is_password_reset_allowed(db, " USER10049@example.test ", request)
