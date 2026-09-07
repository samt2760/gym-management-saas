"""Shared web dependencies and Jinja helpers for server-rendered routes."""

import hashlib
import hmac
import secrets
from collections.abc import Generator

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import SECRET_KEY, TEMPLATES_DIRECTORY
from app.core.database import SessionLocal

templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))

CSRF_COOKIE_NAME = "csrf_token"
CSRF_TOKEN_BYTES = 32


def _csrf_signature(token: str) -> str:
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_csrf_token() -> str:
    token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    return f"{token}.{_csrf_signature(token)}"


def verify_csrf_token(token: str, cookie_token: str | None) -> bool:
    if not token or not cookie_token:
        return False

    if not hmac.compare_digest(token, cookie_token):
        return False

    try:
        raw_token, signature = token.rsplit(".", 1)
    except ValueError:
        return False

    expected_signature = _csrf_signature(raw_token)

    return hmac.compare_digest(signature, expected_signature)


def csrf_token(request: Request) -> str:
    """Return the CSRF token associated with the current request."""
    token = request.cookies.get(CSRF_COOKIE_NAME)

    if token is None:
        token = getattr(request.state, "csrf_token", None)

    if token is None:
        token = create_csrf_token()

    request.state.csrf_token = token
    return token


templates.env.globals["csrf_token"] = csrf_token


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
