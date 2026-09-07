"""Configuration for the current application deployment."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "DATABASE_URL must be set in production."
        )
    DATABASE_URL = "sqlite:///./gym.db"

if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError(
        "Production deployments must use a PostgreSQL DATABASE_URL."
    )

SECRET_KEY = os.getenv("SESSION_SECRET")

if not SECRET_KEY:
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
    raise RuntimeError(
        "SESSION_COOKIE_SECURE must be true in production."
    )

SESSION_COOKIE_SAME_SITE = os.getenv(
    "SESSION_COOKIE_SAME_SITE",
    "lax",
)

PASSWORD_MIN_LENGTH = int(
    os.getenv(
        "PASSWORD_MIN_LENGTH",
        "12",
    )
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

TEMPLATES_DIRECTORY = PROJECT_ROOT / "templates"

STATIC_DIRECTORY = PROJECT_ROOT / "static"
