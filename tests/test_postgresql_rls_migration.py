"""Static regression coverage for the permanent PostgreSQL RLS revision."""

from __future__ import annotations

import importlib

rls_migration = importlib.import_module(
    "migrations.versions.0009_postgresql_tenant_rls"
)


def test_rls_migration_covers_every_direct_tenant_owned_table():
    assert rls_migration.TENANT_TABLES == (
        ("gyms", "id"),
        ("members", "gym_id"),
        ("payments", "gym_id"),
        ("audit_logs", "gym_id"),
        ("legacy_member_records", "gym_id"),
    )


def test_rls_predicate_is_transaction_context_and_fails_closed():
    predicate = rls_migration._tenant_predicate("gym_id")

    assert "current_setting('app.current_gym_id', true)" in predicate
    assert "NULLIF" in predicate
    assert "::integer" in predicate


def test_rls_migration_is_chained_after_the_current_release_head():
    assert rls_migration.down_revision == "0008_payment_legacy_association"
