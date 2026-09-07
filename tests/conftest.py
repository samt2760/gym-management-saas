"""Isolated fixtures for the modular FastAPI application."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-for-authentication"

# DATABASE_URL must be set before importing any application database modules.
from app.core.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None]:
    """Give every test a clean schema without touching the local gym.db."""
    from app.auth import _login_attempts

    _login_attempts.clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        _login_attempts.clear()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def app_module():
    """Expose module-level business helpers used by characterization tests."""
    import app.main

    return app.main


@pytest.fixture()
def public_client() -> Generator[TestClient]:
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture()
def client(db) -> Generator[TestClient]:
    from app.models.gym import Gym
    from app.models.user import User, hash_password

    gym = db.query(Gym).filter(Gym.name == "Primary Gym").first()
    if gym is None:
        gym = Gym(name="Primary Gym", currency="GHS",
                  registration_fee=0, monthly_fee=0)
        db.add(gym)
        db.commit()
        db.refresh(gym)

    admin = db.query(User).filter(User.username == "admin").first()
    if admin is None:
        admin = User(
            username="admin",
            email="admin@example.test",
            password_hash=hash_password("StrongPass!123"),
            status="active",
            is_superuser=True,
            role="OWNER",
            gym_id=gym.id,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

    with TestClient(app, base_url="https://testserver") as test_client:
        # Visit a protected page first so the CSRF cookie is created.
        csrf_response = test_client.get("/dashboard")
        assert csrf_response.status_code == 200

        csrf_token = test_client.cookies.get("csrf_token")
        assert csrf_token

        response = test_client.post(
            "/login",
            data={
                "username": "admin",
                "password": "StrongPass!123",
                "csrf_token": csrf_token,
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        yield test_client


@pytest.fixture()
def db() -> Generator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def pytest_sessionfinish() -> None:
    """Release the shared in-memory test database when pytest finishes."""
    engine.dispose()
