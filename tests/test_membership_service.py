from __future__ import annotations

from datetime import date

import pytest

from app.models import Gym, Member
from app.services.membership_service import (
    MembershipService,
    membership_history,
)


def _make_gym() -> Gym:
    return Gym(
        name="Service Gym", currency="GHS", registration_fee=200, monthly_fee=120
    )


def _make_member() -> Member:
    return Member(
        gym_id=1,
        full_name="Ada Lovelace",
        phone="0240000000",
        email="ada@example.test",
        registration_date=date(2026, 1, 31),
        membership_type="Monthly",
        payment_due_date=date(2026, 2, 28),
        status="Active",
    )


def test_register_membership_records_registration_fee():
    gym = _make_gym()
    member = _make_member()

    created_member, payment = MembershipService.register_member(
        gym,
        member,
        as_of=date(2026, 1, 15),
    )

    assert created_member.status == "Active"
    assert payment.amount == gym.registration_fee
    assert payment.payment_type == "Registration"
    assert created_member.payment_due_date == date(2026, 2, 28)


def test_renewal_rejects_unregistered_member():
    member = _make_member()
    member.registration_date = None

    with pytest.raises(ValueError, match="registered"):
        MembershipService.renew_membership(
            _make_gym(), member, 1, payment_date=date(2026, 3, 1)
        )


def test_invalid_renewal_amount_is_rejected():
    gym = _make_gym()
    member = _make_member()

    with pytest.raises(ValueError, match="multiple of 120"):
        MembershipService.renew_membership(
            gym, member, 130, payment_date=date(2026, 3, 1)
        )


def test_multi_month_renewal_extends_due_date_from_current_expiry():
    gym = _make_gym()
    member = _make_member()
    member.registration_date = date(2026, 1, 1)
    member.payment_due_date = date(2026, 3, 15)

    payment = MembershipService.renew_membership(
        gym, member, gym.monthly_fee * 3, payment_date=date(2026, 3, 1)
    )

    assert payment.amount == 360
    assert member.payment_due_date == date(2026, 6, 15)
    assert member.status == "Active"


def test_freeze_and_cancel_update_status_without_overwriting_expiry():
    member = _make_member()
    member.payment_due_date = date(2026, 4, 30)

    MembershipService.freeze_membership(member)
    assert member.status == "Frozen"

    MembershipService.cancel_membership(member)
    assert member.status == "Cancelled"
    assert member.payment_due_date == date(2026, 4, 30)


def test_membership_history_combines_registration_and_renewal_events():
    member = _make_member()
    member.payment_due_date = date(2026, 4, 30)
    payments = [
        type(
            "Payment",
            (),
            {
                "payment_type": "Registration",
                "payment_date": date(2026, 1, 31),
                "amount": 320,
            },
        )(),
        type(
            "Payment",
            (),
            {
                "payment_type": "Renewal",
                "payment_date": date(2026, 3, 1),
                "amount": 240,
            },
        )(),
    ]

    history = membership_history(member, payments)

    assert [event["event"] for event in history] == ["Registration", "Renewal"]
    assert history[0]["amount"] == 320
    assert history[1]["amount"] == 240
