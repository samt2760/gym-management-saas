from __future__ import annotations

from sqlalchemy import text

from app.core import database, tenant_context
from app.core.tenant_context import (
    TenantContextError,
    bind_tenant_context_to_session,
    clear_tenant_context,
    current_gym_id,
    establish_tenant_context,
    stamp_tenant_context,
)


def test_authenticated_gym_id_is_the_only_tenant_context_source():
    establish_tenant_context(7)

    assert current_gym_id() == 7

    # Request payloads are never accepted by the context helper, so an
    # untrusted value cannot replace the authenticated user's gym id.
    client_supplied_gym_id = 99
    assert current_gym_id() != client_supplied_gym_id

    clear_tenant_context()


def test_authenticated_route_ignores_client_gym_id_and_stamps_user_gym(
    client,
    db,
    monkeypatch,
):
    from app.models import Gym

    authenticated_gym = db.query(Gym).filter(Gym.name == "Primary Gym").one()
    other_gym = Gym(
        name="Other Gym",
        currency="USD",
        registration_fee=40,
        monthly_fee=80,
    )
    db.add(other_gym)
    db.commit()

    stamped_gym_ids: list[int] = []

    def capture_stamp(_connection, gym_id: int) -> None:
        stamped_gym_ids.append(gym_id)

    monkeypatch.setattr(tenant_context, "_set_connection_tenant_context", capture_stamp)
    csrf_token = client.cookies.get("csrf_token")
    assert csrf_token

    response = client.post(
        "/gym-settings",
        data={
            "name": "Authenticated Gym",
            "currency": "GHS",
            "registration_fee": "20",
            "monthly_fee": "120",
            "gym_id": str(other_gym.id),
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    db.refresh(authenticated_gym)
    db.refresh(other_gym)

    assert response.status_code == 303
    assert stamped_gym_ids == [authenticated_gym.id]
    assert authenticated_gym.name == "Authenticated Gym"
    assert other_gym.name == "Other Gym"
    assert current_gym_id() is None


def test_tenant_context_rejects_missing_trusted_gym_id():
    try:
        establish_tenant_context(None)
    except TenantContextError:
        pass
    else:
        raise AssertionError("Tenant context must not default without authentication.")

    assert current_gym_id() is None


def test_get_db_clears_tenant_context_after_request_lifecycle():
    from app.web import get_db

    dependency = get_db()
    next(dependency)
    establish_tenant_context(1)

    dependency.close()

    assert current_gym_id() is None


def test_transaction_hook_restamps_context_after_commit_and_rollback(monkeypatch, db):
    stamped_gym_ids: list[int] = []

    def capture_stamp(_connection, gym_id: int) -> None:
        stamped_gym_ids.append(gym_id)

    monkeypatch.setattr(database, "_set_connection_tenant_context", capture_stamp)
    bind_tenant_context_to_session(db, 1)

    db.execute(text("SELECT 1"))
    db.commit()
    db.execute(text("SELECT 1"))
    db.rollback()
    db.execute(text("SELECT 1"))

    assert stamped_gym_ids == [1, 1, 1]

    clear_tenant_context()


def test_no_tenant_context_does_not_stamp_a_transaction(monkeypatch, db):
    stamped_gym_ids: list[int] = []

    def capture_stamp(_connection, gym_id: int) -> None:
        stamped_gym_ids.append(gym_id)

    monkeypatch.setattr(database, "_set_connection_tenant_context", capture_stamp)

    db.execute(text("SELECT 1"))

    assert stamped_gym_ids == []


def test_session_bound_context_survives_contextvar_worker_boundary(monkeypatch, db):
    stamped_gym_ids: list[int] = []

    monkeypatch.setattr(
        database,
        "_set_connection_tenant_context",
        lambda _connection, gym_id: stamped_gym_ids.append(gym_id),
    )
    bind_tenant_context_to_session(db, 7)
    clear_tenant_context()

    db.execute(text("SELECT 1"))
    db.commit()
    db.execute(text("SELECT 1"))

    assert stamped_gym_ids == [7, 7]


def test_sequential_request_contexts_do_not_leak_between_requests():
    establish_tenant_context(1)
    assert current_gym_id() == 1

    clear_tenant_context()
    establish_tenant_context(2)

    assert current_gym_id() == 2

    clear_tenant_context()
    assert current_gym_id() is None


def test_sqlite_tests_only_verify_application_lifecycle(db):
    establish_tenant_context(1)

    assert stamp_tenant_context(db) is True

    clear_tenant_context()
