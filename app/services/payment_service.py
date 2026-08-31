"""Payment-record creation for the existing registration and renewal flows."""

from __future__ import annotations

from datetime import date

from app.models import Gym, Member, Payment


def registration_payment(
    gym: Gym, member: Member, amount: int, payment_date: date
) -> Payment:
    """Create the current registration record (registration fee only)."""
    return Payment(
        gym_id=gym.id,
        member_id=member.id,
        member_name=member.full_name,
        amount=amount,
        currency=gym.currency,
        payment_date=payment_date,
        membership_type="Monthly",
        payment_type="Registration",
    )


def renewal_payment(gym: Gym, member: Member, amount: int, payment_date: date) -> Payment:
    return Payment(
        gym_id=gym.id,
        member_id=member.id,
        member_name=member.full_name,
        amount=amount,
        currency=gym.currency,
        payment_date=payment_date,
        membership_type="Monthly",
        payment_type="Renewal",
    )
