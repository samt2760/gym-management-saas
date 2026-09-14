"""Regression tests for retry-safe renewals and payment-ledger reporting."""

from datetime import UTC, date, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError

from app.models import Gym, Member, Payment
from app.services.membership_service import MembershipService
from app.services.reporting_service import payment_totals


def _member(db, gym: Gym, *, due_date: date | None = None) -> Member:
    member = Member(
        gym_id=gym.id,
        full_name="Renewal Member",
        phone="0240000000",
        registration_date=date(2026, 1, 1),
        membership_type="Monthly",
        payment_due_date=due_date or (datetime.now(UTC).date() + timedelta(days=10)),
        status="Active",
    )
    db.add(member)
    db.commit()
    return member


def _gym(db, *, name: str = "Renewal Gym") -> Gym:
    gym = Gym(name=name, currency="GHS", registration_fee=20, monthly_fee=120)
    db.add(gym)
    db.commit()
    return gym


def test_same_idempotency_key_returns_original_payment_without_second_extension(db):
    gym = _gym(db)
    member = _member(db, gym)
    original_due_date = member.payment_due_date

    first, replayed = MembershipService.renew_membership_transaction(
        db,
        gym_id=gym.id,
        member_id=member.id,
        amount=120,
        idempotency_key="renewal-retry",
        payment_date=date(2026, 9, 8),
    )
    second, replayed_again = MembershipService.renew_membership_transaction(
        db,
        gym_id=gym.id,
        member_id=member.id,
        amount=120,
        idempotency_key="renewal-retry",
        payment_date=date(2026, 9, 8),
    )

    db.refresh(member)
    assert not replayed
    assert replayed_again
    assert first.id == second.id
    assert member.payment_due_date == original_due_date + relativedelta(months=1)
    assert db.query(Payment).filter(Payment.member_id == member.id).count() == 1


def test_different_idempotency_keys_are_distinct_valid_renewals(db):
    gym = _gym(db)
    member = _member(db, gym)

    MembershipService.renew_membership_transaction(
        db,
        gym_id=gym.id,
        member_id=member.id,
        amount=120,
        idempotency_key="renewal-one",
        payment_date=date(2026, 9, 8),
    )
    MembershipService.renew_membership_transaction(
        db,
        gym_id=gym.id,
        member_id=member.id,
        amount=120,
        idempotency_key="renewal-two",
        payment_date=date(2026, 9, 8),
    )

    assert db.query(Payment).filter(Payment.member_id == member.id).count() == 2


def test_idempotency_key_cannot_be_reused_for_a_different_renewal(db):
    gym = _gym(db)
    first_member = _member(db, gym)
    second_member = _member(db, gym)

    MembershipService.renew_membership_transaction(
        db,
        gym_id=gym.id,
        member_id=first_member.id,
        amount=120,
        idempotency_key="reused-key",
        payment_date=date(2026, 9, 8),
    )

    with pytest.raises(ValueError, match="already used for a different renewal"):
        MembershipService.renew_membership_transaction(
            db,
            gym_id=gym.id,
            member_id=second_member.id,
            amount=120,
            idempotency_key="reused-key",
            payment_date=date(2026, 9, 8),
        )

    assert db.query(Payment).filter(Payment.member_id == second_member.id).count() == 0


def test_failed_renewal_rolls_back_membership_and_payment(db, monkeypatch):
    gym = _gym(db)
    member = _member(db, gym)
    original_due_date = member.payment_due_date

    def fail_flush():
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(db, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        MembershipService.renew_membership_transaction(
            db,
            gym_id=gym.id,
            member_id=member.id,
            amount=120,
            idempotency_key="rollback-case",
            payment_date=date(2026, 9, 8),
        )

    db.expire_all()
    restored = db.query(Member).filter(Member.id == member.id).one()
    assert restored.payment_due_date == original_due_date
    assert db.query(Payment).filter(Payment.member_id == member.id).count() == 0


def test_idempotency_key_is_unique_per_gym_but_not_across_gyms(db):
    gym_a = _gym(db, name="Gym A")
    gym_b = _gym(db, name="Gym B")
    member_a = _member(db, gym_a)
    member_b = _member(db, gym_b)

    for gym, member in ((gym_a, member_a), (gym_b, member_b)):
        db.add(
            Payment(
                gym_id=gym.id,
                member_id=member.id,
                member_name=member.full_name,
                amount=120,
                currency="GHS",
                payment_date=date(2026, 9, 8),
                membership_type="Monthly",
                payment_type="Renewal",
                idempotency_key="same-key",
            )
        )
    db.commit()

    db.add(
        Payment(
            gym_id=gym_a.id,
            member_id=member_a.id,
            member_name=member_a.full_name,
            amount=120,
            currency="GHS",
            payment_date=date(2026, 9, 8),
            membership_type="Monthly",
            payment_type="Renewal",
            idempotency_key="same-key",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_voided_payment_remains_visible_but_is_excluded_from_revenue(db):
    gym = _gym(db)
    member = _member(db, gym)
    completed = Payment(
        gym_id=gym.id,
        member_id=member.id,
        member_name=member.full_name,
        amount=120,
        currency="GHS",
        payment_date=date(2026, 9, 8),
        membership_type="Monthly",
        payment_type="Renewal",
        status="Completed",
    )
    voided = Payment(
        gym_id=gym.id,
        member_id=member.id,
        member_name=member.full_name,
        amount=120,
        currency="GHS",
        payment_date=date(2026, 9, 8),
        membership_type="Monthly",
        payment_type="Renewal",
        status="Voided",
    )
    db.add_all([completed, voided])
    db.commit()

    payments = db.query(Payment).all()
    assert len(payments) == 2
    assert payment_totals(payments, date(2026, 9, 8)) == (120, 120, 120)
