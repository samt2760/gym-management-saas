from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.config import (
    LOGIN_RATE_LIMIT_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAME_SITE,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_SECONDS,
)
from app.core.database import SessionLocal
from app.models import Gym
from app.models.user import (
    PasswordResetToken,
    User,
    UserSession,
    verify_password,
)
from app.web import get_db

RATE_LIMIT_WINDOW = timedelta(seconds=LOGIN_RATE_LIMIT_SECONDS)

_login_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(f"{SECRET_KEY}:{value}".encode()).hexdigest()


def _rate_limit_key(request: Request, email: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}:{email.strip().lower()}"


def is_login_allowed(request: Request, email: str) -> bool:
    key = _rate_limit_key(request, email)
    attempts = _login_attempts[key]
    cutoff = _now_utc() - RATE_LIMIT_WINDOW
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        return False
    attempts.append(_now_utc())
    return True


def get_authenticated_user(request: Request, db: Session) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == _hash_secret(token), UserSession.revoked_at.is_(None))
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    expires_at = _to_utc(session.expires_at)
    if expires_at is None or expires_at <= _now_utc():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    user = db.query(User).filter(User.id == session.user_id,
                                 User.status == "active").first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    request.state.user = user
    return user


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    return get_authenticated_user(request, db)


def get_current_gym(db: Session, user: User) -> Gym:
    if user.gym_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    if gym is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return gym


def get_tenant_object(db: Session, user: User, model, resource_id: int, id_field: str = "id"):
    if user.gym_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    filter_clause = [getattr(model, id_field) ==
                     resource_id, model.gym_id == user.gym_id]
    obj = db.query(model).filter(*filter_clause).first()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return obj


def require_permission(permission: str):
    def dependency(request: Request, user: User = Depends(require_auth)) -> User:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        return user

    return dependency


def require_any_permission(*permissions: str):
    def dependency(request: Request, user: User = Depends(require_auth)) -> User:
        if not any(user.has_permission(permission) for permission in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        return user

    return dependency


def authenticate_user(
    request: Request,
    db: Session,
    email: str,
    password: str,
) -> User | None:
    user = (
        db.query(User)
        .filter(User.email == email.strip().lower())
        .first()
    )

    if user is None or user.status != "active":
        return None

    if not verify_password(password, user.password_hash):
        return None

    user.last_login = _now_utc()
    db.commit()

    return user


def create_session(db: Session, user: User, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_secret(token),
        expires_at=_now_utc() + timedelta(seconds=SESSION_TTL_SECONDS),
        user_agent=request.headers.get("user-agent", "")[:255],
        ip_address=request.client.host if request.client else None,
    )
    db.add(session)
    db.commit()
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAME_SITE,
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        samesite=SESSION_COOKIE_SAME_SITE,
    )


def revoke_all_user_sessions(db: Session, user_id: int) -> None:
    now = _now_utc()
    sessions = db.query(UserSession).filter(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)).all()
    for session in sessions:
        session.revoked_at = now
    db.commit()


def create_password_reset_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_secret(token),
        expires_at=_now_utc() + timedelta(hours=1),
    )
    db.add(reset_token)
    db.commit()
    return token


def resolve_reset_token(db: Session, token: str) -> PasswordResetToken | None:
    if not token:
        return None
    return (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == _hash_secret(token), PasswordResetToken.used_at.is_(None))
        .first()
    )


def redirect_to_login(request: Request, detail: str | None = None) -> RedirectResponse:
    next_path = request.url.path
    if request.query_params:
        next_path = f"{next_path}?{request.url.query}"
    encoded_next = quote(next_path, safe="")
    response = RedirectResponse(
        url=f"/login?next={encoded_next}",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    return response


def require_auth_json(request: Request) -> None:
    db = SessionLocal()
    try:
        get_authenticated_user(request, db)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    finally:
        db.close()


async def auth_middleware(request: Request, call_next):
    protected_paths = [
        "/dashboard",
        "/members",
        "/members/",
        "/payments",
        "/gym-settings",
        "/account",
    ]
    if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and (
        request.url.path in protected_paths
        or request.url.path.startswith("/members/")
        or request.url.path.startswith("/account")
        or request.url.path.startswith("/payments")
        or request.url.path.startswith("/gym-settings")
    ):
        if request.url.path in {"/login", "/logout"}:
            return await call_next(request)
        db = SessionLocal()
        try:
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if not token:
                return redirect_to_login(request)
            session = (
                db.query(UserSession)
                .filter(UserSession.token_hash == _hash_secret(token), UserSession.revoked_at.is_(None))
                .first()
            )
            if session is None:
                return redirect_to_login(request)
            if _to_utc(session.expires_at) is None or _to_utc(session.expires_at) <= _now_utc():
                return redirect_to_login(request)
            user = db.query(User).filter(
                User.id == session.user_id, User.status == "active").first()
            if user is None:
                return redirect_to_login(request)
        finally:
            db.close()
    return await call_next(request)
