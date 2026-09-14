"""Configuration boundaries for web and privileged operational components."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_URL = "postgresql+psycopg://operator:password@db.example.test/gym"


def _run_component_import(statement: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "SESSION_SECRET",
        "SESSION_COOKIE_SECURE",
        "ALLOWED_HOSTS",
    ):
        environment.pop(name, None)
    environment["DATABASE_URL"] = POSTGRES_URL
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_database_configuration_is_scoped_without_web_session_settings():
    result = _run_component_import(
        "import sys; from app.core import database; "
        "assert database.DATABASE_URL == "
        "'postgresql+psycopg://operator:password@db.example.test/gym'; "
        "assert 'app.core.config' not in sys.modules"
    )

    assert result.returncode == 0, result.stderr


def test_bootstrap_import_does_not_load_web_session_configuration():
    result = _run_component_import(
        "import sys; import scripts.bootstrap_first_owner; "
        "assert 'app.core.config' not in sys.modules"
    )

    assert result.returncode == 0, result.stderr


def test_alembic_environment_uses_database_url_without_web_configuration():
    source = (PROJECT_ROOT / "migrations" / "env.py").read_text(encoding="utf-8")

    assert "from app.core.config" not in source
    assert 'os.getenv("DATABASE_URL")' in source
    assert "app.core.database import Base" in source

    environment = os.environ.copy()
    for name in (
        "SESSION_SECRET",
        "SESSION_COOKIE_SECURE",
        "ALLOWED_HOSTS",
    ):
        environment.pop(name, None)
    environment["DATABASE_URL"] = POSTGRES_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    # The legacy first revision inspects a live schema, so offline SQL rendering
    # stops there. Reaching Alembic's PostgreSQL context without a web-secret
    # validation failure proves this operational configuration boundary.
    assert "Context impl PostgresqlImpl" in result.stderr
    assert "SESSION_SECRET environment variable is required" not in result.stderr


def test_backup_ops_runner_does_not_import_web_configuration():
    result = _run_component_import(
        "import sys; import scripts.postgres_archive; "
        "assert 'app.core.config' not in sys.modules"
    )

    assert result.returncode == 0, result.stderr
