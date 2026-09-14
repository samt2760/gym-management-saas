"""Characterization tests for the current membership and payment behavior."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta

from app.models import Gym, Member, Payment
from app.services.membership_service import update_member_status

REGISTRATION_FEE = 200
MONTHLY_FEE = 120


def _csrf_token(client) -> str:
    """Return the CSRF token issued by the application."""
    token = client.cookies.get("csrf_token")

    if not token:
        response = client.get("/dashboard")
        assert response.status_code == 200
        token = client.cookies.get("csrf_token")

    assert token
    return token


def _post(client, url: str, data: dict | None = None, **kwargs):
    """POST with the CSRF token automatically included."""
    payload = dict(data or {})
    payload["csrf_token"] = _csrf_token(client)

    return client.post(
        url,
        data=payload,
        **kwargs,
    )


def configure_gym(client) -> None:
    response = _post(
        client,
        "/gym-settings",
        data={
            "name": "Baseline Gym",
            "currency": "GHS",
            "registration_fee": REGISTRATION_FEE,
            "monthly_fee": MONTHLY_FEE,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def register_member(client, registration_date: date | None = None):
    response = _post(
        client,
        "/members",
        data={
            "full_name": "Ada Lovelace",
            "phone": "0240000000",
            "email": "ada@example.test",
            "date_of_birth": "1990-12-10",
            "registration_date": str(registration_date or datetime.now(UTC).date()),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response


def get_member(db) -> Member:
    member = db.query(Member).one()
    db.refresh(member)
    return member


def test_registration_creates_member_initial_membership_and_registration_payment(
    client, db
):
    configure_gym(client)
    registration_date = date(2026, 1, 31)

    response = register_member(client, registration_date)

    member = get_member(db)
    payment = db.query(Payment).one()

    assert response.headers["location"] == f"/members/{member.id}"
    assert member.full_name == "Ada Lovelace"
    assert member.phone == "0240000000"
    assert member.email == "ada@example.test"
    assert member.registration_date == registration_date
    assert member.membership_type == "Monthly"
    assert member.payment_due_date == registration_date + relativedelta(months=1)
    assert member.status == "Expired"
    assert payment.member_id == member.id
    assert payment.member_name == member.full_name
    assert payment.amount == REGISTRATION_FEE + MONTHLY_FEE
    assert payment.payment_date == registration_date
    assert payment.membership_type == "Monthly"
    assert payment.payment_type == "Registration"


def test_registration_charges_registration_fee_plus_first_month_fee(client, db):
    configure_gym(client)

    register_member(client)

    payment = db.query(Payment).one()
    assert payment.amount == REGISTRATION_FEE + MONTHLY_FEE


def test_registration_requires_configured_positive_monthly_fee(client, db):
    response = _post(
        client,
        "/members",
        data={
            "full_name": "Unconfigured Member",
            "phone": "0200000000",
            "registration_date": str(datetime.now(UTC).date()),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"error": "Gym pricing is not configured correctly."}
    assert db.query(Member).count() == 0
    assert db.query(Payment).count() == 0


def test_single_month_renewal_creates_payment_and_extends_from_current_due_date(
    client, db
):
    configure_gym(client)
    register_member(client)
    member = get_member(db)
    original_due_date = member.payment_due_date

    response = _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": MONTHLY_FEE},
        follow_redirects=False,
    )
    db.refresh(member)
    payments = db.query(Payment).order_by(Payment.id).all()

    assert response.status_code == 303
    assert member.payment_due_date == original_due_date + relativedelta(months=1)
    assert member.status == "Active"
    assert len(payments) == 2
    assert payments[-1].amount == MONTHLY_FEE
    assert payments[-1].payment_type == "Renewal"
    assert payments[-1].payment_date == datetime.now(UTC).date()


def test_multi_month_renewal_extends_membership_by_paid_months(client, db):
    configure_gym(client)
    register_member(client)
    member = get_member(db)
    original_due_date = member.payment_due_date

    response = _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": MONTHLY_FEE * 3},
        follow_redirects=False,
    )

    db.refresh(member)
    renewal = db.query(Payment).order_by(Payment.id.desc()).first()

    assert response.status_code == 303
    assert member.payment_due_date == original_due_date + relativedelta(months=3)
    assert renewal.amount == MONTHLY_FEE * 3
    assert renewal.payment_type == "Renewal"


@pytest.mark.parametrize("amount", [0, -120, 1, 119, 121, 180])
def test_invalid_renewal_amount_does_not_change_membership_or_create_payment(
    client, db, amount
):
    configure_gym(client)
    register_member(client)
    member = get_member(db)
    original_due_date = member.payment_due_date
    original_payment_count = db.query(Payment).count()

    response = _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": amount},
    )

    db.refresh(member)

    assert response.status_code == 200
    assert response.json() == {
        "error": f"Invalid payment amount. Enter a multiple of {MONTHLY_FEE}."
    }
    assert member.payment_due_date == original_due_date
    assert db.query(Payment).count() == original_payment_count


def test_expired_member_renewal_restarts_from_today(client, db):
    configure_gym(client)
    register_member(client, datetime.now(UTC).date() - relativedelta(months=3))
    member = get_member(db)

    assert member.payment_due_date < datetime.now(UTC).date()

    response = _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": MONTHLY_FEE * 2},
        follow_redirects=False,
    )

    db.refresh(member)

    assert response.status_code == 303
    assert member.payment_due_date == datetime.now(UTC).date() + relativedelta(months=2)
    assert member.status == "Active"


def test_status_calculation_marks_due_today_active_and_past_due_expired(db):
    gym = Gym(
        name="Status Test Gym",
        currency="GHS",
        registration_fee=200,
        monthly_fee=120,
    )
    db.add(gym)
    db.flush()

    today_member = Member(
        gym_id=gym.id,
        full_name="Due Today",
        phone="0200000001",
        registration_date=datetime.now(UTC).date(),
        payment_due_date=datetime.now(UTC).date(),
        status="Expired",
    )

    expired_member = Member(
        gym_id=gym.id,
        full_name="Past Due",
        phone="0200000002",
        registration_date=datetime.now(UTC).date() - timedelta(days=2),
        payment_due_date=datetime.now(UTC).date() - timedelta(days=1),
        status="Active",
    )

    db.add_all([today_member, expired_member])
    db.commit()

    update_member_status(db)

    db.refresh(today_member)
    db.refresh(expired_member)

    assert today_member.status == "Active"
    assert expired_member.status == "Expired"


def test_member_detail_shows_payment_history(client, db):
    configure_gym(client)
    register_member(client)
    member = get_member(db)

    _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": MONTHLY_FEE},
    )

    response = client.get(f"/members/{member.id}")
    page = " ".join(response.text.split())

    assert response.status_code == 200
    assert "Payment History" in page
    assert "Registration" in page
    assert "Renewal" in page
    assert "GHS 320.00" in page
    assert "GHS 120.00" in page


def test_member_deletion_soft_deletes_member_and_preserves_payment_history(client, db):
    configure_gym(client)
    register_member(client)
    member = get_member(db)

    _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": MONTHLY_FEE},
    )

    response = _post(
        client,
        f"/members/{member.id}/delete",
        follow_redirects=False,
    )

    payments = db.query(Payment).order_by(Payment.id).all()

    assert response.status_code == 303
    assert response.headers["location"] == "/members"
    db.refresh(member)
    assert db.query(Member).count() == 1
    assert member.deleted_at is not None
    assert len(payments) == 2
    assert all(payment.member_id == member.id for payment in payments)
    assert all(payment.member_name == "Ada Lovelace" for payment in payments)


def test_dashboard_calculates_membership_and_revenue_totals(client, db):
    configure_gym(client)
    register_member(client)
    member = get_member(db)

    _post(
        client,
        f"/members/{member.id}/renew",
        data={"amount": MONTHLY_FEE * 2},
    )

    response = client.get("/dashboard")
    page = " ".join(response.text.split())

    assert response.status_code == 200
    assert "Total Members" in page
    assert "Active Members" in page

    # The three dashboard revenue cards should each render the same total for
    # this registration-plus-first-month and multi-month renewal scenario.
    assert page.count("GHS 560.00") == 3


def test_gym_settings_update_pricing_and_reject_invalid_monthly_fee(client, db):
    configure_gym(client)
    gym = db.query(Gym).one()

    assert gym.name == "Baseline Gym"
    assert gym.currency == "GHS"
    assert gym.registration_fee == REGISTRATION_FEE
    assert gym.monthly_fee == MONTHLY_FEE

    response = _post(
        client,
        "/gym-settings",
        data={
            "name": "Baseline Gym",
            "currency": "GHS",
            "registration_fee": REGISTRATION_FEE,
            "monthly_fee": 0,
        },
    )

    db.refresh(gym)

    assert response.status_code == 200
    assert response.json() == {"error": "Monthly renewal fee must be greater than zero"}
    assert gym.monthly_fee == MONTHLY_FEE
