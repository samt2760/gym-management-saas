"""Transactional creation of the first tenant and owner account.

This service is deliberately reachable only through the operator CLI.  It is
not a web workflow and it is safe to invoke once: any existing gym or user
causes the operation to fail before a record is created.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.password_policy import PASSWORD_MIN_LENGTH
from app.models.gym import Gym
from app.models.user import Role, User, hash_password


class BootstrapError(RuntimeError):
    """Base error for a refused or failed first-owner bootstrap."""


class BootstrapAlreadyInitializedError(BootstrapError):
    """Raised when the target database already contains application identity data."""


class BootstrapPrivilegeError(BootstrapError):
    """Raised when PostgreSQL cannot safely create the first RLS-protected tenant."""


@dataclass(frozen=True)
class FirstOwnerBootstrap:
    gym_name: str
    currency: str
    registration_fee: int
    monthly_fee: int
    username: str
    email: str
    password: str


@dataclass(frozen=True)
class BootstrapResult:
    gym_id: int
    owner_id: int


def _validate(request: FirstOwnerBootstrap) -> FirstOwnerBootstrap:
    gym_name = request.gym_name.strip()
    username = request.username.strip()
    email = request.email.strip().lower()
    currency = request.currency.strip().upper()

    if not gym_name:
        raise BootstrapError("Gym name is required.")
    if not username or len(username) > 64:
        raise BootstrapError("Username must contain between 1 and 64 characters.")
    if not email or len(email) > 255 or "@" not in email:
        raise BootstrapError("A valid owner email address is required.")
    if len(currency) != 3 or not currency.isalpha():
        raise BootstrapError("Currency must be a three-letter ISO 4217 code.")
    if request.registration_fee < 0 or request.monthly_fee < 0:
        raise BootstrapError("Fees must be non-negative integer minor units.")
    if len(request.password) < PASSWORD_MIN_LENGTH:
        raise BootstrapError(
            f"Owner password must be at least {PASSWORD_MIN_LENGTH} characters."
        )

    return FirstOwnerBootstrap(
        gym_name=gym_name,
        currency=currency,
        registration_fee=request.registration_fee,
        monthly_fee=request.monthly_fee,
        username=username,
        email=email,
        password=request.password,
    )


def _require_bootstrap_operator(session: Session) -> None:
    """Require a controlled PostgreSQL role that can initialize forced RLS tables.

    ``gyms`` is itself protected with FORCE RLS, so an empty database has no
    tenant context from which an ordinary runtime role can create its first
    row.  Only a separately held, short-lived operator role with BYPASSRLS may
    use this command.  SQLite is retained for isolated unit tests only.
    """

    if session.bind is None or session.bind.dialect.name != "postgresql":
        return

    bypasses_rls = session.execute(
        text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).scalar_one_or_none()
    if bypasses_rls is not True:
        raise BootstrapPrivilegeError(
            "First-owner bootstrap requires a dedicated PostgreSQL "
            "BYPASSRLS operator role; the runtime role is not permitted."
        )


def bootstrap_first_owner(
    session: Session, request: FirstOwnerBootstrap
) -> BootstrapResult:
    """Atomically create the sole initial gym and login-capable owner.

    The caller owns the session lifecycle.  On every failure this function
    rolls back the transaction so a failed bootstrap cannot leave a partial
    gym or user record behind.
    """

    validated = _validate(request)
    try:
        _require_bootstrap_operator(session)

        if (
            session.query(Gym.id).first() is not None
            or session.query(User.id).first() is not None
        ):
            raise BootstrapAlreadyInitializedError(
                "Bootstrap refused: the database already contains a gym or user."
            )

        gym = Gym(
            name=validated.gym_name,
            currency=validated.currency,
            registration_fee=validated.registration_fee,
            monthly_fee=validated.monthly_fee,
        )
        session.add(gym)
        session.flush()

        owner = User(
            gym_id=gym.id,
            username=validated.username,
            email=validated.email,
            password_hash=hash_password(validated.password),
            status="active",
            role=Role.OWNER.value,
            is_superuser=True,
        )
        session.add(owner)
        session.flush()
        session.commit()
        return BootstrapResult(gym_id=gym.id, owner_id=owner.id)
    except Exception:
        session.rollback()
        raise
