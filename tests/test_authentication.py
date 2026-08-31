from __future__ import annotations

import hashlib
from datetime import date

from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.models import Gym, Member, Payment
from app.models.user import User


def _create_gym(db, name: str = "Primary Gym", currency: str = "GHS") -> Gym:
    gym = db.query(Gym).filter(Gym.name == name).first()
    if gym is None:
        gym = Gym(name=name, currency=currency, registration_fee=200, monthly_fee=120)
        db.add(gym)
        db.commit()
        db.refresh(gym)
    return gym


def _create_user(
    db,
    username: str = "admin",
    password: str = "StrongPass!123",
    role: str = "OWNER",
    gym: Gym | None = None,
) -> User:
    gym = gym or _create_gym(db)
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        user = User(
            username=username,
            email=f"{username}@example.test",
            password_hash=hashlib.sha256(password.encode()).hexdigest(),
            status="active",
            is_superuser=(role == "OWNER"),
            role=role,
            gym_id=gym.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def test_login_authenticates_and_sets_secure_session(public_client, db):
    _create_user(db)

    response = public_client.post(
        "/login",
        data={"username": "admin", "password": "StrongPass!123"},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/dashboard"
    assert "session" in response.headers["set-cookie"].lower()
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()


def test_login_rejects_invalid_credentials_without_disclosing_user_presence(public_client, db):
    _create_user(db)

    response = public_client.post(
        "/login",
        data={"username": "admin", "password": "wrong-password"},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Invalid username or password."}
    assert "admin" not in response.text.lower()
    assert "wrong-password" not in response.text.lower()


def test_authenticated_routes_require_login(public_client):
    response = public_client.get("/dashboard", follow_redirects=False)

    assert response.status_code == status.HTTP_307_TEMPORARY_REDIRECT
    assert response.headers["location"] == "/login?next=%2Fdashboard"


def test_password_change_requires_current_password_and_updates_hash(client, db):
    user = _create_user(db)
    client.post(
        "/login",
        data={"username": "admin", "password": "StrongPass!123"},
        follow_redirects=False,
    )

    response = client.post(
        "/account/password",
        data={
            "current_password": "StrongPass!123",
            "new_password": "NewStrongPass!456",
        },
        follow_redirects=False,
    )

    db.refresh(user)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"detail": "Password updated successfully."}
    assert user.password_hash != hashlib.sha256(
        "StrongPass!123".encode()).hexdigest()
    assert user.password_hash.startswith("$2b$")


def test_logout_clears_session(public_client, db):
    _create_user(db)
    public_client.post(
        "/login",
        data={"username": "admin", "password": "StrongPass!123"},
        follow_redirects=False,
    )

    response = public_client.post("/logout", follow_redirects=False)

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/login"
    assert "expires=" in response.headers["set-cookie"].lower()


def test_users_without_members_delete_permission_cannot_delete_members(public_client, db):
    _create_user(db, username="receptionist", password="StrongPass!123", role="RECEPTIONIST")
    _create_user(db, username="member-owner", password="StrongPass!123", role="OWNER")

    with TestClient(app, base_url="https://testserver") as owner_client:
        response = owner_client.post(
            "/login",
            data={"username": "member-owner", "password": "StrongPass!123"},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER

        response = owner_client.post(
            "/gym-settings",
            data={
                "name": "RBAC Gym",
                "currency": "GHS",
                "registration_fee": "200",
                "monthly_fee": "120",
            },
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER

        response = owner_client.post(
            "/members",
            data={
                "full_name": "Unauthorized Target",
                "phone": "5551234567",
                "registration_date": "2026-08-30",
            },
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        member_id = 1

    with TestClient(app, base_url="https://testserver") as receptionist_client:
        response = receptionist_client.post(
            "/login",
            data={"username": "receptionist", "password": "StrongPass!123"},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER

        response = receptionist_client.post(f"/members/{member_id}/delete", follow_redirects=False)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {"detail": "Permission denied."}


def test_users_without_settings_edit_permission_cannot_update_gym_settings(public_client, db):
    _create_user(db, username="trainer", password="StrongPass!123", role="TRAINER")
    response = public_client.post(
        "/login",
        data={"username": "trainer", "password": "StrongPass!123"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER

    response = public_client.post(
        "/gym-settings",
        data={
            "name": "Updated Gym",
            "currency": "USD",
            "registration_fee": "10",
            "monthly_fee": "30",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Permission denied."}


def test_gym_a_user_cannot_access_gym_b_member_or_payment(public_client, db):
    gym_a = _create_gym(db, name="Gym A")
    gym_b = _create_gym(db, name="Gym B")
    _create_user(db, username="gym_a_owner", password="StrongPass!123", role="OWNER", gym=gym_a)
    _create_user(db, username="gym_b_owner", password="StrongPass!123", role="OWNER", gym=gym_b)

    member_b = Member(
        gym_id=gym_b.id,
        full_name="Gym B Member",
        phone="5550000000",
        email="gymb@example.test",
        registration_date=date(2026, 8, 22),
        membership_type="Monthly",
        payment_due_date=date(2026, 9, 22),
        status="Active",
    )
    db.add(member_b)
    db.commit()
    db.refresh(member_b)

    payment_b = Payment(
        gym_id=gym_b.id,
        member_id=member_b.id,
        member_name=member_b.full_name,
        amount=250,
        currency="GHS",
        payment_date=date(2026, 8, 25),
        membership_type="Monthly",
        payment_type="Renewal",
    )
    db.add(payment_b)
    db.commit()

    with TestClient(app, base_url="https://testserver") as gym_a_client:
        response = gym_a_client.post(
            "/login",
            data={"username": "gym_a_owner", "password": "StrongPass!123"},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER

        response = gym_a_client.get(f"/members/{member_b.id}", follow_redirects=False)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {"detail": "Access denied."}

        response = gym_a_client.post(f"/members/{member_b.id}/delete", follow_redirects=False)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == {"detail": "Access denied."}

        response = gym_a_client.get("/payments", follow_redirects=False)
        assert response.status_code == status.HTTP_200_OK
        assert "Gym B Member" not in response.text
        assert "gymb@example.test" not in response.text
