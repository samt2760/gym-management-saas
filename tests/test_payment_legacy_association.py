"""Focused SQLite coverage for Mission 9's portable ORM/schema behavior."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Gym, LegacyMemberRecord, Member, Payment


def _gym(db, name: str) -> Gym:
    gym = Gym(name=name, currency="GHS", registration_fee=0, monthly_fee=120)
    db.add(gym)
    db.commit()
    return gym


def _member(db, gym: Gym) -> Member:
    member = Member(
        gym_id=gym.id,
        full_name="Normal Member",
        phone="5550100",
        registration_date=date(2026, 8, 1),
        payment_due_date=date(2026, 9, 1),
        status="Active",
    )
    db.add(member)
    db.commit()
    return member


def _legacy(db, gym: Gym, source_reference: str = "legacy-test") -> LegacyMemberRecord:
    legacy = LegacyMemberRecord(
        gym_id=gym.id,
        record_kind="ARCHIVED_LEGACY_MEMBER",
        reason_code="UNLINKED_HISTORICAL_PAYMENT",
        source_reference=source_reference,
    )
    db.add(legacy)
    db.commit()
    return legacy


def _payment(gym: Gym, **values) -> Payment:
    return Payment(
        gym_id=gym.id,
        member_name="ledger snapshot",
        amount=120,
        currency="GHS",
        payment_date=date(2026, 8, 28),
        membership_type="Monthly",
        payment_type="Registration",
        **values,
    )


def test_payment_with_only_member_association_succeeds(db):
    gym = _gym(db, "Member Gym")
    member = _member(db, gym)
    db.add(_payment(gym, member_id=member.id))
    db.commit()


def test_payment_with_only_legacy_association_succeeds(db):
    gym = _gym(db, "Legacy Gym")
    legacy = _legacy(db, gym)
    db.add(_payment(gym, legacy_member_record_id=legacy.id))
    db.commit()


@pytest.mark.parametrize("association", [{}, {"member_id": 1, "legacy_member_record_id": 1}])
def test_payment_requires_exactly_one_association(db, association):
    gym = _gym(db, "Invariant Gym")
    member = _member(db, gym)
    legacy = _legacy(db, gym)
    if association:
        association = {"member_id": member.id, "legacy_member_record_id": legacy.id}
    db.add(_payment(gym, **association))
    with pytest.raises(IntegrityError):
        db.commit()


def test_cross_tenant_legacy_association_fails(db):
    first_gym = _gym(db, "First Gym")
    second_gym = _gym(db, "Second Gym")
    legacy = _legacy(db, second_gym)
    db.add(_payment(first_gym, legacy_member_record_id=legacy.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_source_reference_is_unique_per_gym_but_reusable_by_another_gym(db):
    first_gym = _gym(db, "First Gym")
    second_gym = _gym(db, "Second Gym")
    _legacy(db, first_gym, "legacy-payment-9")
    _legacy(db, second_gym, "legacy-payment-9")
    db.add(LegacyMemberRecord(
        gym_id=first_gym.id,
        record_kind="ARCHIVED_LEGACY_MEMBER",
        reason_code="UNLINKED_HISTORICAL_PAYMENT",
        source_reference="legacy-payment-9",
    ))
    with pytest.raises(IntegrityError):
        db.commit()


def test_legacy_records_are_not_normal_members(db):
    gym = _gym(db, "Counts Gym")
    _legacy(db, gym)
    assert db.query(Member).filter(Member.gym_id == gym.id).count() == 0
