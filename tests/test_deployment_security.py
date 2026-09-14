"""Regression coverage for production deployment security defaults."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.responses import Response

import app.main as main_module

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _production_import(
    environment: dict[str, str | None], *, module: str = "app.core.config"
) -> subprocess.CompletedProcess[str]:
    values = os.environ.copy()
    values.update(
        {
            "ENVIRONMENT": "production",
            "DATABASE_URL": "postgresql+psycopg://user:password@db/gym",
            "ALLOWED_HOSTS": "gym.example.test",
            **environment,
        }
    )
    if environment.get("ALLOWED_HOSTS") is None:
        values.pop("ALLOWED_HOSTS", None)
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=PROJECT_ROOT,
        env=values,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_configuration_fails_fast_for_missing_secret_and_insecure_cookie():
    missing_secret = _production_import(
        {"SESSION_SECRET": "", "SESSION_COOKIE_SECURE": "true"}
    )
    assert missing_secret.returncode != 0
    assert "SESSION_SECRET environment variable is required" in missing_secret.stderr

    insecure_cookie = _production_import(
        {"SESSION_SECRET": "test-production-secret", "SESSION_COOKIE_SECURE": "false"}
    )
    assert insecure_cookie.returncode != 0
    assert "SESSION_COOKIE_SECURE must be true" in insecure_cookie.stderr


@pytest.mark.parametrize(
    ("environment", "message", "module"),
    [
        (
            {"SESSION_SECRET": "replace-me", "SESSION_COOKIE_SECURE": "true"},
            "SESSION_SECRET environment variable is required",
            "app.core.config",
        ),
        (
            {
                "SESSION_SECRET": "test-production-secret",
                "SESSION_COOKIE_SECURE": "true",
                "ALLOWED_HOSTS": "",
            },
            "ALLOWED_HOSTS contains an invalid production host",
            "app.main as runtime; runtime._get_allowed_hosts()",
        ),
        (
            {
                "DATABASE_URL": "sqlite:///production.db",
                "SESSION_SECRET": "test-production-secret",
                "SESSION_COOKIE_SECURE": "true",
            },
            "Production deployments must use a PostgreSQL DATABASE_URL",
            "app.core.config",
        ),
    ],
)
def test_production_configuration_rejects_other_invalid_web_settings(
    environment, message, module
):
    result = _production_import(environment, module=module)

    assert result.returncode != 0
    assert message in result.stderr


def test_valid_production_web_configuration_still_initializes():
    result = _production_import(
        {
            "SESSION_SECRET": "test-production-secret",
            "SESSION_COOKIE_SECURE": "true",
        }
    )

    assert result.returncode == 0, result.stderr


def test_security_headers_and_cache_control_apply_to_login(public_client):
    response = public_client.get("/login")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert (
        response.headers["permissions-policy"]
        == "camera=(), microphone=(), geolocation=()"
    )
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert (
        "style-src 'self' 'unsafe-inline'"
        in response.headers["content-security-policy"]
    )
    assert "strict-transport-security" not in response.headers


def test_hsts_is_only_emitted_for_production(monkeypatch):
    response = Response()
    monkeypatch.setattr(main_module, "ENVIRONMENT", "production")

    main_module._apply_security_headers(response)

    assert (
        response.headers["strict-transport-security"]
        == "max-age=31536000; includeSubDomains"
    )


def test_production_requires_explicit_valid_allowed_hosts(monkeypatch):
    monkeypatch.setattr(main_module, "ENVIRONMENT", "production")
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        main_module._get_allowed_hosts()

    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="invalid production host"):
        main_module._get_allowed_hosts()

    monkeypatch.setenv("ALLOWED_HOSTS", "gym.example.test,admin.example.test")
    assert main_module._get_allowed_hosts() == [
        "gym.example.test",
        "admin.example.test",
    ]


def test_static_paths_are_not_forced_to_no_store(public_client):
    response = public_client.get("/static/not-present.css")

    assert "cache-control" not in response.headers
