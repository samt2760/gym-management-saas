"""Configuration for the current application deployment."""

from __future__ import annotations

import os

from app.core.database_settings import DATABASE_URL, PROJECT_ROOT

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("Production deployments must use a PostgreSQL DATABASE_URL.")

SECRET_KEY = os.getenv("SESSION_SECRET")

if not SECRET_KEY or (
    ENVIRONMENT == "production" and SECRET_KEY.startswith("replace-")
):
    raise RuntimeError(
        "SESSION_SECRET environment variable is required. "
        "Set a strong random secret before starting the application."
    )

SESSION_COOKIE_NAME = os.getenv(
    "SESSION_COOKIE_NAME",
    "session",
)

SESSION_TTL_SECONDS = int(
    os.getenv(
        "SESSION_TTL_SECONDS",
        "28800",
    )
)

SESSION_COOKIE_SECURE = (
    os.getenv(
        "SESSION_COOKIE_SECURE",
        "false",
    ).lower()
    == "true"
)

if ENVIRONMENT == "production" and not SESSION_COOKIE_SECURE:
    raise RuntimeError("SESSION_COOKIE_SECURE must be true in production.")

SESSION_COOKIE_SAME_SITE = os.getenv(
    "SESSION_COOKIE_SAME_SITE",
    "lax",
)

MAX_LOGIN_ATTEMPTS = int(
    os.getenv(
        "MAX_LOGIN_ATTEMPTS",
        "5",
    )
)

LOGIN_RATE_LIMIT_SECONDS = int(
    os.getenv(
        "LOGIN_RATE_LIMIT_SECONDS",
        "600",
    )
)

PASSWORD_RESET_TOKEN_TTL_SECONDS = int(
    os.getenv(
        "PASSWORD_RESET_TOKEN_TTL_SECONDS",
        "3600",
    )
)

PASSWORD_RESET_RATE_LIMIT_SECONDS = int(
    os.getenv(
        "PASSWORD_RESET_RATE_LIMIT_SECONDS",
        "600",
    )
)

PASSWORD_RESET_MAX_REQUESTS = int(
    os.getenv(
        "PASSWORD_RESET_MAX_REQUESTS",
        "3",
    )
)

TEMPLATES_DIRECTORY = PROJECT_ROOT / "templates"

STATIC_DIRECTORY = PROJECT_ROOT / "static"
