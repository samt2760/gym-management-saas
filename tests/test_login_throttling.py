"""Regression tests for database-backed login throttling."""

from datetime import UTC, datetime, timedelta

from fastapi import status

from app.models import AuditLog, Gym, LoginThrottle
from app.models.user import User, UserSession, hash_password

PASSWORD = "StrongPass!123"


def _user(db) -> User:
    gym = Gym(name="Throttle Gym", currency="GHS", registration_fee=0, monthly_fee=0)
    db.add(gym)
    db.flush()
    user = User(
        gym_id=gym.id,
        username="throttle-user",
        email="throttle@example.test",
        password_hash=hash_password(PASSWORD),
        status="active",
        role="OWNER",
        is_superuser=True,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, *, username: str, password: str):
    client.get("/login")
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": client.cookies.get("csrf_token"),
        },
        follow_redirects=False,
    )


def test_failed_logins_are_hashed_database_state_and_threshold_is_enforced(
    public_client, db, monkeypatch
):
    user = _user(db)
    monkeypatch.setattr("app.services.login_throttle_service.MAX_LOGIN_ATTEMPTS", 2)
    monkeypatch.setattr("app.services.login_throttle_service.LOGIN_RATE_LIMIT_SECONDS", 60)

    for _ in range(2):
        response = _login(public_client, username=user.username, password="incorrect")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json() == {"detail": "Invalid email or password."}

    throttle = db.query(LoginThrottle).one()
    assert throttle.failure_count == 2
    assert throttle.locked_until is not None
    assert user.email not in throttle.key_hash
    assert user.username not in throttle.key_hash
    assert "incorrect" not in throttle.key_hash

    blocked = _login(public_client, username=user.username, password=PASSWORD)
    assert blocked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert db.query(UserSession).count() == 0
    assert db.query(AuditLog).filter(AuditLog.action == "auth.login_succeeded").count() == 0


def test_successful_login_clears_database_throttle_and_records_audit(public_client, db):
    user = _user(db)
    failed = _login(public_client, username="  THROTTLE-USER  ", password="incorrect")
    assert failed.status_code == status.HTTP_401_UNAUTHORIZED
    assert db.query(LoginThrottle).count() == 1

    success = _login(public_client, username=user.username, password=PASSWORD)
    assert success.status_code == status.HTTP_303_SEE_OTHER
    assert db.query(LoginThrottle).count() == 0
    assert db.query(UserSession).filter(UserSession.user_id == user.id).count() == 1
    assert db.query(AuditLog).filter(
        AuditLog.action == "auth.login_succeeded", AuditLog.actor_user_id == user.id
    ).count() == 1


def test_expired_throttle_allows_login_again(public_client, db, monkeypatch):
    user = _user(db)
    monkeypatch.setattr("app.services.login_throttle_service.MAX_LOGIN_ATTEMPTS", 1)

    assert _login(public_client, username=user.username, password="incorrect").status_code == 401
    throttle = db.query(LoginThrottle).one()
    throttle.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    response = _login(public_client, username=user.username, password=PASSWORD)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert db.query(LoginThrottle).count() == 0


def test_nonexistent_identifier_keeps_generic_response_and_uses_database_state(
    public_client, db
):
    response = _login(public_client, username="unknown-user", password="incorrect")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid email or password."}
    assert db.query(LoginThrottle).count() == 1
