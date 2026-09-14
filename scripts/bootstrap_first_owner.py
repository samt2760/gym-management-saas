"""One-shot operator command for initializing a fresh production database.

The command never accepts a password on its command line.  Supply
``BOOTSTRAP_OWNER_PASSWORD`` through an operator-controlled secret injection
mechanism, or enter it interactively when prompted.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.bootstrap_service import (
    BootstrapError,
    FirstOwnerBootstrap,
    bootstrap_first_owner,
)

CONFIRMATION = "INITIALIZE_EMPTY_DATABASE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True, help=f"Must equal {CONFIRMATION}.")
    parser.add_argument("--gym-name", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--registration-fee", required=True, type=int)
    parser.add_argument("--monthly-fee", required=True, type=int)
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    return parser.parse_args()


def _read_password() -> str:
    password = os.getenv("BOOTSTRAP_OWNER_PASSWORD")
    if password is not None:
        return password
    return getpass.getpass("Initial owner password: ")


def main() -> int:
    args = parse_args()
    if args.confirm != CONFIRMATION:
        print(
            "Bootstrap refused: explicit confirmation was not supplied.",
            file=sys.stderr,
        )
        return 2

    session = SessionLocal()
    try:
        result = bootstrap_first_owner(
            session,
            FirstOwnerBootstrap(
                gym_name=args.gym_name,
                currency=args.currency,
                registration_fee=args.registration_fee,
                monthly_fee=args.monthly_fee,
                username=args.username,
                email=args.email,
                password=_read_password(),
            ),
        )
    except BootstrapError as error:
        print(f"Bootstrap refused: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print(
        f"First-owner bootstrap completed (gym_id={result.gym_id}, owner_id={result.owner_id})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
