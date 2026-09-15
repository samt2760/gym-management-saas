"""Membership lifecycle rules centralized in one dedicated service."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Gym, Member, Payment, User
from app.services.audit_service import record_audit


def _utc_today() -> date:
    return datetime.now(UTC).date()


def get_or_create_gym(db: Session) -> Gym:
    gym = db.query(Gym).order_by(Gym.id.asc()).first()
    if gym is None:
        gym = Gym(name="My Gym", currency="GHS", registration_fee=0, monthly_fee=0)
        db.add(gym)
        db.commit()
        db.refresh(gym)
    return gym


def update_member_status(db: Session, gym_id: int | None = None) -> None:
    today = _utc_today()
    changed = False
    query = db.query(Member).filter(Member.deleted_at.is_(None))
    if gym_id is not None:
        query = query.filter(Member.gym_id == gym_id)

    for member in query.all():
        original_status = member.status
        new_status = MembershipService.refresh_status(member, today)
        if original_status != new_status:
            member.status = new_status
            changed = True
    if changed:
        db.commit()


def registration_due_date(registration_date: date) -> date:
    return registration_date + relativedelta(months=1)


def renewal_start_date(member: Member, today: date | None = None) -> date:
    effective_today = today or _utc_today()
    if member.payment_due_date is None or member.payment_due_date < effective_today:
        return effective_today
    return member.payment_due_date


def extend_membership(
    member: Member, months_paid: int, today: date | None = None
) -> None:
    effective_today = today or _utc_today()
    member.payment_due_date = renewal_start_date(
        member, effective_today
    ) + relativedelta(months=months_paid)
    member.status = "Active"


def membership_history(
    member: Member, payments: Iterable[Payment]
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for payment in sorted(
        payments,
        key=lambda item: (
            getattr(item, "payment_date", date.min),
            getattr(item, "id", 0),
        ),
    ):
        events.append(
            {
                "event": getattr(payment, "payment_type", "Unknown"),
                "amount": payment.amount,
                "payment_date": payment.payment_date,
                "currency": getattr(payment, "currency", "GHS"),
            }
        )
    return events


class MembershipService:
    @staticmethod
    def utc_today() -> date:
        return _utc_today()

    @staticmethod
    def validate_pricing(gym: Gym) -> None:
        if gym is None:
            raise ValueError("Gym pricing is not configured correctly.")
        if gym.registration_fee < 0 or gym.monthly_fee <= 0:
            raise ValueError("Gym pricing is not configured correctly.")

    @staticmethod
    def refresh_status(member: Member, as_of: date | None = None) -> str:
        effective_date = as_of or _utc_today()
        if member.status in {"Frozen", "Cancelled"}:
            return member.status
        new_status = (
            "Active" if member.payment_due_date >= effective_date else "Expired"
        )
        member.status = new_status
        return member.status

    @staticmethod
    def register_member(
        gym: Gym,
        member: Member,
        *,
        registration_date: date | None = None,
        payment_date: date | None = None,
        as_of: date | None = None,
    ) -> tuple[Member, Payment]:
        MembershipService.validate_pricing(gym)
        if member is None:
            raise ValueError("Member is required.")

        effective_date = as_of or _utc_today()
        effective_registration_date = (
            registration_date or member.registration_date or effective_date
        )
        effective_payment_date = payment_date or _utc_today()
        member.registration_date = effective_registration_date
        member.membership_type = "Monthly"
        member.payment_due_date = registration_due_date(effective_registration_date)
        member.status = (
            "Active" if member.payment_due_date >= effective_date else "Expired"
        )
        payment_amount = gym.registration_fee
        payment = Payment(
            gym_id=gym.id,
            member_id=member.id,
            member_name=member.full_name,
            amount=payment_amount,
            currency=gym.currency,
            payment_date=effective_payment_date,
            membership_type="Monthly",
            payment_type="Registration",
        )
        if member.id is not None:
            payment.member_id = member.id
        return member, payment

    @staticmethod
    def renew_membership(
        gym: Gym,
        member: Member,
        amount: int,
        *,
        payment_date: date | None = None,
        months: int | None = None,
    ) -> Payment:
        MembershipService.validate_pricing(gym)
        if member is None:
            raise ValueError("Member is required.")
        if member.registration_date is None:
            raise ValueError("Member must be registered before renewal.")

        if amount <= 0 or gym.monthly_fee <= 0:
            raise ValueError(
                f"Invalid payment amount. Enter a multiple of {gym.monthly_fee}."
            )

        if months is None:
            months = amount // gym.monthly_fee

        if (
            months <= 0
            or amount % gym.monthly_fee != 0
            or amount != gym.monthly_fee * months
        ):
            raise ValueError(
                f"Invalid payment amount. Enter a multiple of {gym.monthly_fee}."
            )

        effective_payment_date = payment_date or _utc_today()
        start_date = renewal_start_date(member, effective_payment_date)
        member.payment_due_date = start_date + relativedelta(months=months)
        member.status = "Active"

        payment = Payment(
            gym_id=gym.id,
            member_id=member.id,
            member_name=member.full_name,
            amount=amount,
            currency=gym.currency,
            payment_date=effective_payment_date,
            membership_type="Monthly",
            payment_type="Renewal",
        )
        return payment

    @staticmethod
    def renew_membership_transaction(
        db: Session,
        *,
        gym_id: int,
        member_id: int,
        amount: int,
        idempotency_key: str,
        payment_date: date | None = None,
        actor: User | None = None,
    ) -> tuple[Payment, bool]:
        """Atomically apply a retry-safe renewal for one tenant member."""
        existing = (
            db.query(Payment)
            .filter(
                Payment.gym_id == gym_id,
                Payment.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            if (
                existing.member_id != member_id
                or existing.amount != amount
                or existing.payment_type != "Renewal"
            ):
                raise ValueError(
                    "Idempotency key was already used for a different renewal."
                )
            return existing, True

        try:
            # PostgreSQL locks only this member. SQLite safely ignores the
            # clause while retaining the unique-key idempotency guarantee.
            member = (
                db.query(Member)
                .filter(
                    Member.id == member_id,
                    Member.gym_id == gym_id,
                    Member.deleted_at.is_(None),
                )
                .with_for_update()
                .first()
            )
            if member is None:
                raise PermissionError("Access denied.")

            # Recheck after acquiring the lock for a request that waited.
            existing = (
                db.query(Payment)
                .filter(
                    Payment.gym_id == gym_id,
                    Payment.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing is not None:
                if (
                    existing.member_id != member_id
                    or existing.amount != amount
                    or existing.payment_type != "Renewal"
                ):
                    raise ValueError(
                        "Idempotency key was already used for a different renewal."
                    )
                db.commit()
                return existing, True

            gym = db.query(Gym).filter(Gym.id == gym_id).first()
            if gym is None:
                raise PermissionError("Access denied.")

            payment = MembershipService.renew_membership(
                gym, member, amount, payment_date=payment_date
            )
            payment.idempotency_key = idempotency_key
            db.add(payment)
            # Assign the payment ID before creating its linked audit record.
            # A flush failure rolls back the entitlement and both audit events.
            db.flush()
            record_audit(
                db,
                gym_id=gym_id,
                actor=actor,
                action="membership.renewed",
                resource_type="member",
                resource_id=member.id,
                details={"months_paid": amount // gym.monthly_fee},
            )
            record_audit(
                db,
                gym_id=gym_id,
                actor=actor,
                action="payment.created",
                resource_type="payment",
                resource_id=payment.id,
                details={"payment_type": "Renewal", "amount_minor": amount},
            )
            db.commit()
            db.refresh(payment)
            return payment, False
        except IntegrityError:
            db.rollback()
            # A competing request may have won the database unique-key race.
            existing = (
                db.query(Payment)
                .filter(
                    Payment.gym_id == gym_id,
                    Payment.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing is not None:
                if (
                    existing.member_id != member_id
                    or existing.amount != amount
                    or existing.payment_type != "Renewal"
                ):
                    raise ValueError(
                        "Idempotency key was already used for a different renewal."
                    )
                return existing, True
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def freeze_membership(member: Member) -> Member:
        member.status = "Frozen"
        return member

    @staticmethod
    def cancel_membership(member: Member) -> Member:
        member.status = "Cancelled"
        return member
