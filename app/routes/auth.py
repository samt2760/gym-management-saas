from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    _hash_secret,
    authenticate_user,
    create_password_reset_token,
    create_session,
    is_login_allowed,
    require_auth,
    resolve_reset_token,
    revoke_all_user_sessions,
)
from app.core.config import PASSWORD_MIN_LENGTH, SESSION_COOKIE_NAME
from app.models.user import User, UserSession, hash_password, verify_password
from app.web import get_db, templates

router = APIRouter()


def _safe_next_url(next_url: str | None) -> str:
    """
    Allow only local application paths as post-login destinations.

    External URLs such as https://example.com are rejected to prevent
    an open-redirect vulnerability.
    """

    if not next_url:
        return "/dashboard"

    parsed = urlparse(next_url)

    if parsed.scheme or parsed.netloc:
        return "/dashboard"

    if not next_url.startswith("/"):
        return "/dashboard"

    if next_url.startswith("//"):
        return "/dashboard"

    return next_url


@router.get("/login")
def login_page(
    request: Request,
    next: str | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": _safe_next_url(next),
        },
    )


@router.post("/login")
def login(
    request: Request,
    email: str | None = Form(None),
    username: str | None = Form(None),
    password: str = Form(...),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    """
    Authenticate a user using either email or username.

    Email is the preferred login identifier for the current UI.
    Username remains supported for backwards compatibility and
    existing application clients/tests.
    """

    identifier = (
        email.strip().lower()
        if email and email.strip()
        else username.strip().lower()
        if username and username.strip()
        else ""
    )

    if not identifier:
        return JSONResponse(
            {
                "detail": "Email or username is required."
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not is_login_allowed(request, identifier):
        return JSONResponse(
            {
                "detail": (
                    "Too many login attempts. "
                    "Please try again later."
                )
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # authenticate_user() currently authenticates by email.
    # If the caller supplied a username, resolve it to the
    # user's email first.
    authentication_email = identifier

    if not email:
        matched_user = (
            db.query(User)
            .filter(
                User.username == identifier
            )
            .first()
        )

        if matched_user is not None:
            authentication_email = matched_user.email

    user = authenticate_user(
        request,
        db,
        authentication_email,
        password,
    )

    if user is None:
        return JSONResponse(
            {
                "detail": "Invalid email or password."
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_session(
        db,
        user,
        request,
    )

    response = RedirectResponse(
        url=_safe_next_url(next),
        status_code=status.HTTP_303_SEE_OTHER,
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=(
            request.url.hostname
            not in {"127.0.0.1", "localhost"}
        ),
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )

    return response


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    token = request.cookies.get(
        SESSION_COOKIE_NAME
    )

    if token:
        session = (
            db.query(UserSession)
            .filter(
                UserSession.token_hash == _hash_secret(token),
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
            .first()
        )

        if session is not None:
            session.revoked_at = datetime.now(UTC)
            db.commit()

    response = RedirectResponse(
        url="/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
    )

    return response


@router.post("/account/password")
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    if not verify_password(
        current_password,
        user.password_hash,
    ):
        return JSONResponse(
            {
                "detail": (
                    "Current password is incorrect."
                )
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if len(new_password) < PASSWORD_MIN_LENGTH:
        return JSONResponse(
            {
                "detail": (
                    f"New password must be at least "
                    f"{PASSWORD_MIN_LENGTH} characters long."
                )
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.password_hash = hash_password(
        new_password
    )

    revoke_all_user_sessions(
        db,
        user.id,
    )

    db.commit()

    return {
        "detail": "Password updated successfully."
    }


@router.post("/account/password/reset-request")
def request_password_reset(
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(
            User.email == email.strip().lower()
        )
        .first()
    )

    if user is not None:
        create_password_reset_token(
            db,
            user,
        )

    return {
        "detail": (
            "If the account exists, "
            "a reset link has been sent."
        )
    }


@router.post("/account/password/reset")
def reset_password(
    token: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    reset = resolve_reset_token(
        db,
        token,
    )

    now = datetime.now(UTC)

    if reset is None or reset.expires_at <= now:
        return JSONResponse(
            {
                "detail": (
                    "Invalid or expired reset token."
                )
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = (
        db.query(User)
        .filter(
            User.id == reset.user_id
        )
        .first()
    )

    if user is None:
        return JSONResponse(
            {
                "detail": (
                    "Invalid or expired reset token."
                )
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(new_password) < PASSWORD_MIN_LENGTH:
        return JSONResponse(
            {
                "detail": (
                    f"New password must be at least "
                    f"{PASSWORD_MIN_LENGTH} characters long."
                )
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.password_hash = hash_password(
        new_password
    )

    reset.used_at = now

    revoke_all_user_sessions(
        db,
        user.id,
    )

    db.commit()

    return {
        "detail": "Password reset successfully."
    }


@router.get("/account")
def account_summary(
    request: Request,
    user: User = Depends(require_auth),
):
    return {
        "username": user.username,
        "status": user.status,
    }
