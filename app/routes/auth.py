from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
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


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": next or "/dashboard"},
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    if not is_login_allowed(request, username):
        return JSONResponse({"detail": "Too many login attempts. Please try again later."}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    user = authenticate_user(request, db, username, password)
    if user is None:
        return JSONResponse({"detail": "Invalid username or password."}, status_code=status.HTTP_401_UNAUTHORIZED)

    token = create_session(db, user, request)
    response = RedirectResponse(
        url=next or "/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/",
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        from app.auth import _hash_secret

        session = (
            db.query(UserSession)
            .filter(UserSession.token_hash == _hash_secret(token), UserSession.revoked_at.is_(None))
            .first()
        )
        if session is not None:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()

    response = RedirectResponse(
        url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.post("/account/password")
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    if not verify_password(current_password, user.password_hash):
        return JSONResponse({"detail": "Current password is incorrect."}, status_code=status.HTTP_401_UNAUTHORIZED)
    if len(new_password) < PASSWORD_MIN_LENGTH:
        return JSONResponse(
            {"detail": f"New password must be at least {PASSWORD_MIN_LENGTH} characters long."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.password_hash = hash_password(new_password)
    revoke_all_user_sessions(db, user.id)
    db.commit()
    return {"detail": "Password updated successfully."}


@router.post("/account/password/reset-request")
def request_password_reset(email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if user is not None:
        create_password_reset_token(db, user)
    return {"detail": "If the account exists, a reset link has been sent."}


@router.post("/account/password/reset")
def reset_password(token: str = Form(...), new_password: str = Form(...), db: Session = Depends(get_db)):
    reset = resolve_reset_token(db, token)
    now = datetime.now(timezone.utc)
    if reset is None or reset.expires_at <= now:
        return JSONResponse({"detail": "Invalid or expired reset token."}, status_code=status.HTTP_400_BAD_REQUEST)
    user = db.query(User).filter(User.id == reset.user_id).first()
    if user is None:
        return JSONResponse({"detail": "Invalid or expired reset token."}, status_code=status.HTTP_400_BAD_REQUEST)
    if len(new_password) < PASSWORD_MIN_LENGTH:
        return JSONResponse(
            {"detail": f"New password must be at least {PASSWORD_MIN_LENGTH} characters long."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.password_hash = hash_password(new_password)
    reset.used_at = now
    revoke_all_user_sessions(db, user.id)
    db.commit()
    return {"detail": "Password reset successfully."}


@router.get("/account")
def account_summary(request: Request, user: User = Depends(require_auth)):
    return {"username": user.username, "status": user.status}
