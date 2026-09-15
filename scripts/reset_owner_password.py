"""Controlled operator command for resetting an existing owner's password."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal
from app.core.password_policy import PASSWORD_MIN_LENGTH
from app.core.tenant_context import bind_tenant_context_to_session
from app.models import Gym
from app.models.user import Role, User, hash_password
from app.services.audit_service import record_audit
from app.services.session_service import revoke_all_user_sessions

CONFIRMATION = "RESET_OWNER_PASSWORD"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Must equal {CONFIRMATION}.",
    )
    parser.add_argument("--gym-id", required=True, type=int)
    parser.add_argument("--username", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.confirm != CONFIRMATION:
        print(
            "Password reset refused: explicit confirmation was not supplied.",
            file=sys.stderr,
        )
        return 2

    password = getpass.getpass("New owner password: ")
    confirmation = getpass.getpass("Confirm new owner password: ")

    if password != confirmation:
        print("Password reset refused: passwords do not match.", file=sys.stderr)
        return 2
    if len(password) < PASSWORD_MIN_LENGTH:
        print(
            f"Password reset refused: password must be at least {PASSWORD_MIN_LENGTH} characters long.",
            file=sys.stderr,
        )
        return 2

    session = SessionLocal()

    try:
        # The explicit gym target is the operator's trusted scope for this
        # non-web command. Binding it before querying also preserves forced-RLS
        # protection for the tenant-owned gym and audit tables.
        bind_tenant_context_to_session(session, args.gym_id)
        gym = session.query(Gym).filter(Gym.id == args.gym_id).first()
        if gym is None:
            print("Password reset refused: target gym was not found.", file=sys.stderr)
            return 1

        user = (
            session.query(User)
            .filter(
                User.gym_id == gym.id,
                User.username == args.username.strip().lower(),
            )
            .first()
        )

        if user is None:
            print("Password reset refused: owner was not found.", file=sys.stderr)
            return 1

        if user.role.upper() != Role.OWNER.value:
            print(
                "Password reset refused: selected user is not an owner.",
                file=sys.stderr,
            )
            return 1

        if user.status != "active":
            print(
                "Password reset refused: selected owner is not active.",
                file=sys.stderr,
            )
            return 1

        user.password_hash = hash_password(password)
        revoke_all_user_sessions(session, user.id, commit=False)
        record_audit(
            session,
            gym_id=gym.id,
            action="auth.owner_password_reset",
            resource_type="user",
            resource_id=user.id,
            details={"source": "operator_cli"},
        )
        session.commit()

        print(
            "Owner password reset successfully "
            f"(gym_id={gym.id}, username={user.username})."
        )
        return 0

    except SQLAlchemyError:
        session.rollback()
        print("Password reset failed due to a database error.", file=sys.stderr)
        return 1

    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
