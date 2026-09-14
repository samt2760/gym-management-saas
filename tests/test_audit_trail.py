"""Audit trail and tenant-isolation regression coverage."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditLog, Gym, Member, Payment, User
from app.models.user import hash_password
from app.services.audit_service import audit_records_for_user
from app.services.membership_service import MembershipService


def _csrf_post(client: TestClient, url: str, data: dict[str, str], **kwargs):
    return client.post(
        url,
        data={"csrf_token": client.cookies.get("csrf_token"), **data},
        **kwargs,
    )


def _create_user(db, gym: Gym, username: str) -> User:
    user = User(
        gym_id=gym.id,
        username=username,
        email=f"{username}@example.test",
        password_hash=hash_password("StrongPass!123"),
        status="active",
        role="OWNER",
        is_superuser=True,
    )
    db.add(user)
    db.commit()
    return user


def test_registration_and_renewal_audit_actor_tenant_and_targets(client, db):
    gym = db.query(Gym).filter(Gym.name == "Primary Gym").one()
    user = db.query(User).filter(User.username == "admin").one()
    gym.registration_fee = 20
    gym.monthly_fee = 120
    db.commit()

    created = _csrf_post(
        client,
        "/members",
        {
            "full_name": "Audited Member",
            "phone": "0240000000",
            "registration_date": "2026-09-08",
            "email": "audited@example.test",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    member = db.query(Member).filter(Member.full_name == "Audited Member").one()
    registration_payment = (
        db.query(Payment).filter(Payment.member_id == member.id).one()
    )

    registration_events = (
        db.query(AuditLog)
        .filter(
            AuditLog.gym_id == gym.id,
            AuditLog.action.in_(["member.created", "payment.created"]),
        )
        .all()
    )
    assert {event.action for event in registration_events} == {
        "member.created",
        "payment.created",
    }
    assert all(event.actor_user_id == user.id for event in registration_events)
    assert {event.resource_id for event in registration_events} == {
        member.id,
        registration_payment.id,
    }

    renewed = _csrf_post(
        client,
        f"/members/{member.id}/renew",
        {"amount": "120", "idempotency_key": "audited-renewal"},
        follow_redirects=False,
    )
    assert renewed.status_code == 303
    renewal_payment = (
        db.query(Payment).filter(Payment.idempotency_key == "audited-renewal").one()
    )
    renewal_events = (
        db.query(AuditLog)
        .filter(
            AuditLog.action.in_(["membership.renewed", "payment.created"]),
            AuditLog.resource_id.in_([member.id, renewal_payment.id]),
        )
        .all()
    )
    assert {event.action for event in renewal_events} == {
        "membership.renewed",
        "payment.created",
    }
    assert all(
        event.gym_id == gym.id and event.actor_user_id == user.id
        for event in renewal_events
    )

    before_failed_renewal = db.query(AuditLog).count()
    failed = _csrf_post(
        client,
        f"/members/{member.id}/renew",
        {"amount": "1", "idempotency_key": "invalid-renewal"},
    )
    assert failed.status_code == 200
    assert db.query(AuditLog).count() == before_failed_renewal


def test_rolled_back_renewal_does_not_leave_audit_event(db, monkeypatch):
    gym = Gym(
        name="Rollback Audit Gym", currency="GHS", registration_fee=20, monthly_fee=120
    )
    db.add(gym)
    db.commit()
    actor = _create_user(db, gym, "rollback-auditor")
    member = Member(
        gym_id=gym.id,
        full_name="Rollback Member",
        phone="0240000001",
        registration_date=date(2026, 1, 1),
        membership_type="Monthly",
        payment_due_date=date(2026, 10, 1),
        status="Active",
    )
    db.add(member)
    db.commit()

    monkeypatch.setattr(
        db, "flush", lambda: (_ for _ in ()).throw(RuntimeError("flush failed"))
    )
    with pytest.raises(RuntimeError, match="flush failed"):
        MembershipService.renew_membership_transaction(
            db,
            gym_id=gym.id,
            member_id=member.id,
            amount=120,
            idempotency_key="rollback-audit",
            actor=actor,
        )

    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.gym_id == gym.id).count() == 0
    assert db.query(Payment).filter(Payment.member_id == member.id).count() == 0


def test_authentication_audit_events_do_not_store_credentials(public_client, db):
    gym = Gym(
        name="Authentication Audit Gym",
        currency="GHS",
        registration_fee=0,
        monthly_fee=0,
    )
    db.add(gym)
    db.commit()
    user = _create_user(db, gym, "audit-login-user")
    public_client.get("/login")

    response = _csrf_post(
        public_client,
        "/login",
        {"username": user.username, "password": "StrongPass!123", "next": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    login_event = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "auth.login_succeeded", AuditLog.actor_user_id == user.id
        )
        .one()
    )
    assert login_event.gym_id == gym.id
    assert login_event.resource_id == user.id
    assert "StrongPass!123" not in str(login_event.details)

    response = _csrf_post(public_client, "/logout", {}, follow_redirects=False)
    assert response.status_code == 303
    assert (
        db.query(AuditLog)
        .filter(AuditLog.action == "auth.logout", AuditLog.actor_user_id == user.id)
        .count()
        == 1
    )


def test_cross_gym_member_mutations_reporting_and_audit_access_are_isolated(
    public_client, db
):
    gym_a = Gym(
        name="Audit Gym A", currency="GHS", registration_fee=20, monthly_fee=120
    )
    gym_b = Gym(
        name="Audit Gym B", currency="GHS", registration_fee=20, monthly_fee=120
    )
    db.add_all([gym_a, gym_b])
    db.commit()
    user_a = _create_user(db, gym_a, "audit-gym-a")
    user_b = _create_user(db, gym_b, "audit-gym-b")
    member_b = Member(
        gym_id=gym_b.id,
        full_name="Gym B Protected Member",
        phone="0240000002",
        registration_date=date(2026, 1, 1),
        membership_type="Monthly",
        payment_due_date=datetime.now(UTC).date() + timedelta(days=20),
        status="Active",
        deleted_at=datetime.now(UTC),
    )
    db.add(member_b)
    db.commit()

    with TestClient(app, base_url="https://testserver") as gym_a_client:
        gym_a_client.get("/login")
        login = _csrf_post(
            gym_a_client,
            "/login",
            {
                "username": user_a.username,
                "password": "StrongPass!123",
                "next": "/dashboard",
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        for url, data in (
            (
                f"/members/{member_b.id}/edit",
                {
                    "full_name": "Changed",
                    "phone": "0240000002",
                    "registration_date": "2026-01-01",
                },
            ),
            (f"/members/{member_b.id}/delete", {}),
            (f"/members/{member_b.id}/restore", {}),
            (
                f"/members/{member_b.id}/renew",
                {"amount": "120", "idempotency_key": "gym-b-key"},
            ),
        ):
            result = _csrf_post(gym_a_client, url, data, follow_redirects=False)
            assert result.status_code == 403
        assert "Gym B Protected Member" not in gym_a_client.get("/dashboard").text

    assert member_b.deleted_at is not None
    assert db.query(Payment).filter(Payment.gym_id == gym_a.id).count() == 0
    assert all(event.gym_id == gym_a.id for event in audit_records_for_user(db, user_a))

    # Gym B's own record remains available only in its tenant-scoped audit query.
    with TestClient(app, base_url="https://testserver") as gym_b_client:
        gym_b_client.get("/login")
        login = _csrf_post(
            gym_b_client,
            "/login",
            {
                "username": user_b.username,
                "password": "StrongPass!123",
                "next": "/dashboard",
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        restored = _csrf_post(
            gym_b_client, f"/members/{member_b.id}/restore", {}, follow_redirects=False
        )
        assert restored.status_code == 303
    assert all(event.gym_id == gym_b.id for event in audit_records_for_user(db, user_b))
