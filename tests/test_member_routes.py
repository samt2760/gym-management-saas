from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import Gym, Member, Payment
from app.models.user import User, hash_password


def _today() -> date:
    return datetime.now(UTC).date()


def _csrf_token(client: TestClient) -> str:
    token = client.cookies.get("csrf_token")
    if not token:
        response = client.get("/dashboard")
        assert response.status_code == 200
        token = client.cookies.get("csrf_token")
    assert token
    return token


def _post(client: TestClient, url: str, data: dict, **kwargs):
    payload = dict(data)
    payload["csrf_token"] = _csrf_token(client)
    return client.post(url, data=payload, **kwargs)


def _configure_gym(client: TestClient) -> None:
    response = _post(
        client,
        "/gym-settings",
        {
            "name": "Route Test Gym",
            "currency": "GHS",
            "registration_fee": "200",
            "monthly_fee": "120",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _register(client: TestClient) -> int:
    response = _post(
        client,
        "/members",
        {
            "full_name": "Route Member",
            "phone": "0240000000",
            "email": "route@example.test",
            "registration_date": str(_today()),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def test_member_lifecycle_preserves_import_and_payment_history(client, db):
    _configure_gym(client)

    existing_due_date = _today() + timedelta(days=20)
    response = _post(
        client,
        "/members/existing",
        {
            "full_name": "Imported Member",
            "phone": "0241111111",
            "email": "imported@example.test",
            "registration_date": str(_today() - timedelta(days=60)),
            "payment_due_date": str(existing_due_date),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    imported_id = int(response.headers["location"].rsplit("/", 1)[1])
    imported = db.get(Member, imported_id)
    assert imported is not None
    assert imported.payment_due_date == existing_due_date
    assert db.query(Payment).filter(Payment.member_id == imported_id).count() == 0

    response = client.get(f"/members/{imported_id}")
    assert response.status_code == 200
    assert "Imported Member" in response.text

    response = _post(
        client,
        f"/members/{imported_id}/edit",
        {
            "full_name": "Edited Imported Member",
            "phone": "0242222222",
            "email": "edited@example.test",
            "registration_date": str(_today() - timedelta(days=60)),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(imported)
    assert imported.full_name == "Edited Imported Member"
    assert imported.payment_due_date == existing_due_date

    response = _post(
        client,
        f"/members/{imported_id}/renew",
        {"amount": "120"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(imported)
    assert imported.payment_due_date > existing_due_date
    assert db.query(Payment).filter(Payment.member_id == imported_id).count() == 1

    response = _post(
        client,
        f"/members/{imported_id}/delete",
        {},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(imported)
    assert imported.deleted_at is not None
    assert db.query(Payment).filter(Payment.member_id == imported_id).count() == 1

    response = client.get("/members")
    assert response.status_code == 200
    assert "Edited Imported Member" not in response.text

    response = client.get("/members/deleted")
    assert response.status_code == 200
    assert "Edited Imported Member" in response.text

    response = _post(
        client,
        f"/members/{imported_id}/restore",
        {},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db.refresh(imported)
    assert imported.deleted_at is None
    assert "Edited Imported Member" in client.get("/members").text


def test_deleted_members_and_restore_are_tenant_scoped(client, db):
    gym_a = db.query(Gym).filter(Gym.name == "Primary Gym").first()
    assert gym_a is not None
    gym_a.registration_fee = 200
    gym_a.monthly_fee = 120
    gym_b = Gym(
        name="Second Route Gym",
        currency="GHS",
        registration_fee=200,
        monthly_fee=120,
    )
    db.add(gym_b)
    db.flush()
    user_b = User(
        username="second-route-owner",
        email="second-route-owner@example.test",
        password_hash=hash_password("StrongPass!123"),
        status="active",
        is_superuser=True,
        role="OWNER",
        gym_id=gym_b.id,
    )
    member_b = Member(
        gym_id=gym_b.id,
        full_name="Second Gym Deleted",
        phone="0243333333",
        registration_date=_today() - timedelta(days=30),
        membership_type="Monthly",
        payment_due_date=_today() + timedelta(days=10),
        status="Active",
        deleted_at=datetime.now(UTC),
    )
    db.add_all([user_b, member_b])
    db.commit()
    db.refresh(member_b)

    response = client.get("/members/deleted")
    assert response.status_code == 200
    assert "Second Gym Deleted" not in response.text

    with TestClient(app, base_url="https://testserver") as client_b:
        response = client_b.post(
            "/login",
            data={
                "username": "second-route-owner",
                "password": "StrongPass!123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "Second Gym Deleted" in client_b.get("/members/deleted").text

        response = _post(
            client,
            f"/members/{member_b.id}/restore",
            {},
            follow_redirects=False,
        )
        assert response.status_code == 403
        db.refresh(member_b)
        assert member_b.deleted_at is not None
