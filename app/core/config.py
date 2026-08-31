"""Configuration for the current application deployment."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gym.db")
SECRET_KEY = os.getenv("SECRET_KEY", "replace-me-with-a-strong-random-secret")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "session")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "28800"))
SESSION_COOKIE_SECURE = os.getenv(
    "SESSION_COOKIE_SECURE", "true").lower() == "true"
SESSION_COOKIE_SAME_SITE = os.getenv("SESSION_COOKIE_SAME_SITE", "lax")
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "12"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_SECONDS", "600"))
TEMPLATES_DIRECTORY = PROJECT_ROOT / "templates"
STATIC_DIRECTORY = PROJECT_ROOT / "static"
