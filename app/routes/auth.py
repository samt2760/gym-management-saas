from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    _hash_secret,
    authenticate_user,
    clear_session_cookie,
    create_password_reset_token,
    create_session,
    is_password_reset_allowed,
    login_throttle_key,
    require_auth,
    resolve_reset_token,
    set_session_cookie,
)
from app.core.config import SESSION_COOKIE_NAME
from app.core.password_policy import PASSWORD_MIN_LENGTH
from app.core.tenant_context import (
    bind_tenant_context_to_session,
    establish_tenant_context,
    stamp_tenant_context,
)
from app.models.user import User, UserSession, hash_password, verify_password
from app.services.audit_service import record_audit
from app.services.login_throttle_service import (
    acquire_login_throttle,
    clear_login_throttle,
    record_failed_login,
)
from app.services.password_reset_delivery import (
    PasswordResetMessage,
    get_password_reset_delivery,
)
from app.services.session_service import revoke_all_user_sessions
from app.web import get_db, templates

router = APIRouter()
logger = logging.getLogger(__name__)


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
            {"detail": "Email or username is required."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # authenticate_user() currently authenticates by email.
    # If the caller supplied a username, resolve it to the
    # user's email first.
    authentication_email = identifier

    if not email:
        matched_user = db.query(User).filter(User.username == identifier).first()

        if matched_user is not None:
            authentication_email = matched_user.email

    throttle = acquire_login_throttle(
        db,
        key_hash=login_throttle_key(request, authentication_email),
        now=datetime.now(UTC),
    )
    if throttle is None:
        logger.warning("Login attempt throttled")
        return JSONResponse(
            {"detail": "Too many login attempts. Please try again later."},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = authenticate_user(
        request,
        db,
        authentication_email,
        password,
        commit=False,
    )

    if user is None:
        record_failed_login(db, throttle, datetime.now(UTC))
        return JSONResponse(
            {"detail": "Invalid email or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_session(
        db,
        user,
        request,
        commit=False,
    )
    establish_tenant_context(user.gym_id)
    bind_tenant_context_to_session(db, user.gym_id)
    stamp_tenant_context(db)
    clear_login_throttle(db, throttle)
    record_audit(
        db,
        gym_id=user.gym_id,
        actor=user,
        action="auth.login_succeeded",
        resource_type="user",
        resource_id=user.id,
    )
    db.commit()

    response = RedirectResponse(
        url=_safe_next_url(next),
        status_code=status.HTTP_303_SEE_OTHER,
    )

    set_session_cookie(response, token)

    return response


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    token = request.cookies.get(SESSION_COOKIE_NAME)

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
            record_audit(
                db,
                gym_id=user.gym_id,
                actor=user,
                action="auth.logout",
                resource_type="user_session",
                resource_id=session.id,
            )
            db.commit()

    response = RedirectResponse(
        url="/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    clear_session_cookie(response)

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
            {"detail": ("Current password is incorrect.")},
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

    user.password_hash = hash_password(new_password)

    revoke_all_user_sessions(
        db,
        user.id,
        commit=False,
    )
    record_audit(
        db,
        gym_id=user.gym_id,
        actor=user,
        action="auth.password_changed",
        resource_type="user",
        resource_id=user.id,
    )

    db.commit()

    return {"detail": "Password updated successfully."}


@router.post("/account/password/reset-request")
def request_password_reset(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    normalized_email = email.strip().lower()
    generic_message = "If the account exists, a reset link has been sent."

    if not is_password_reset_allowed(db, normalized_email, request):
        logger.warning("Password reset request rate-limited")
        return templates.TemplateResponse(
            request=request,
            name="password_reset_request.html",
            context={"message": generic_message},
        )

    user = (
        db.query(User)
        .filter(
            User.email == normalized_email,
            User.status == "active",
        )
        .first()
    )

    if user is not None:
        token = create_password_reset_token(
            db,
            user,
        )
        reset_url = str(request.url_for("reset_password_page"))
        reset_url = f"{reset_url}?{urlencode({'token': token})}"
        get_password_reset_delivery().deliver(
            PasswordResetMessage(
                recipient=user.email,
                reset_url=reset_url,
            )
        )
        logger.info("Password reset message generated")

    return templates.TemplateResponse(
        request=request,
        name="password_reset_request.html",
        context={"message": generic_message},
    )


@router.get("/account/password/forgot")
def password_reset_request_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="password_reset_request.html",
        context={},
    )


@router.get("/account/password/reset")
def reset_password_page(request: Request, token: str = ""):
    return templates.TemplateResponse(
        request=request,
        name="password_reset.html",
        context={"token": token},
    )


@router.post("/account/password/reset")
def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    reset = resolve_reset_token(
        db,
        token,
    )

    if reset is None:
        logger.warning("Invalid or expired password reset attempt")
        return templates.TemplateResponse(
            request=request,
            name="password_reset.html",
            context={"token": token, "error": "Invalid or expired reset token."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = db.query(User).filter(User.id == reset.user_id).first()
    if user is None:
        return templates.TemplateResponse(
            request=request,
            name="password_reset.html",
            context={
                "token": token,
                "error": "Invalid or expired reset token.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not new_password or len(new_password) < PASSWORD_MIN_LENGTH:
        return templates.TemplateResponse(
            request=request,
            name="password_reset.html",
            context={
                "token": token,
                "error": f"New password must be at least {PASSWORD_MIN_LENGTH} characters long.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="password_reset.html",
            context={
                "token": token,
                "error": "Passwords do not match.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    now = datetime.now(UTC)
    establish_tenant_context(user.gym_id)
    bind_tenant_context_to_session(db, user.gym_id)
    stamp_tenant_context(db)
    user.password_hash = hash_password(new_password)
    reset.used_at = now
    revoke_all_user_sessions(db, user.id, commit=False)
    record_audit(
        db,
        gym_id=user.gym_id,
        actor=user,
        action="auth.password_reset_succeeded",
        resource_type="user",
        resource_id=user.id,
    )
    db.commit()
    logger.info("Password reset completed")

    return templates.TemplateResponse(
        request=request,
        name="password_reset.html",
        context={"success": "Password reset successfully. Please sign in again."},
    )


@router.get("/account")
def account_summary(
    request: Request,
    user: User = Depends(require_auth),
):
    return {
        "username": user.username,
        "status": user.status,
    }
