from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.config import (
    PASSWORD_RESET_MAX_REQUESTS,
    PASSWORD_RESET_RATE_LIMIT_SECONDS,
    PASSWORD_RESET_TOKEN_TTL_SECONDS,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAME_SITE,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_SECONDS,
)
from app.core.database import SessionLocal
from app.core.tenant_context import (
    TenantContextError,
    bind_tenant_context_to_session,
    establish_tenant_context,
    stamp_tenant_context,
)
from app.models import Gym
from app.models.user import (
    PasswordResetToken,
    User,
    UserSession,
    verify_password,
)
from app.web import get_db

_unknown_reset_attempts: OrderedDict[str, deque[datetime]] = OrderedDict()
_MAX_UNKNOWN_RESET_KEYS = 10000


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


def login_throttle_key(request: Request, identifier: str) -> str:
    """Hash the normalized identifier and direct client address for storage."""
    client_ip = request.client.host if request.client else "unknown"
    return _hash_secret(f"login-throttle:{client_ip}:{identifier.strip().lower()}")


def get_authenticated_user(request: Request, db: Session) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    session = (
        db.query(UserSession)
        .filter(
            UserSession.token_hash == _hash_secret(token),
            UserSession.revoked_at.is_(None),
        )
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    expires_at = _to_utc(session.expires_at)
    if expires_at is None or expires_at <= _now_utc():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    user = (
        db.query(User)
        .filter(User.id == session.user_id, User.status == "active")
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    request.state.user = user
    return user


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_authenticated_user(request, db)
    try:
        establish_tenant_context(user.gym_id)
        bind_tenant_context_to_session(db, user.gym_id)
    except TenantContextError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        ) from exc
    stamp_tenant_context(db)
    return user


def get_current_gym(db: Session, user: User) -> Gym:
    if user.gym_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    if gym is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )
    return gym


def get_tenant_object(
    db: Session, user: User, model, resource_id: int, id_field: str = "id"
):
    if user.gym_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )
    filter_clause = [
        getattr(model, id_field) == resource_id,
        model.gym_id == user.gym_id,
    ]
    obj = db.query(model).filter(*filter_clause).first()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )
    return obj


def require_permission(permission: str):
    def dependency(request: Request, user: User = Depends(require_auth)) -> User:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied."
            )
        return user

    return dependency


def require_any_permission(*permissions: str):
    def dependency(request: Request, user: User = Depends(require_auth)) -> User:
        if not any(user.has_permission(permission) for permission in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied."
            )
        return user

    return dependency


def authenticate_user(
    request: Request,
    db: Session,
    email: str,
    password: str,
    *,
    commit: bool = True,
) -> User | None:
    user = db.query(User).filter(User.email == email.strip().lower()).first()

    if user is None or user.status != "active":
        return None

    if not verify_password(password, user.password_hash):
        return None

    user.last_login = _now_utc()
    if commit:
        db.commit()

    return user


def create_session(
    db: Session, user: User, request: Request, *, commit: bool = True
) -> str:
    token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_secret(token),
        expires_at=_now_utc() + timedelta(seconds=SESSION_TTL_SECONDS),
        user_agent=request.headers.get("user-agent", "")[:255],
        ip_address=request.client.host if request.client else None,
    )
    db.add(session)
    if commit:
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


def _prune_reset_attempts(attempts: deque[datetime], now: datetime) -> None:
    cutoff = now - timedelta(seconds=PASSWORD_RESET_RATE_LIMIT_SECONDS)
    while attempts and attempts[0] < cutoff:
        attempts.popleft()


def is_password_reset_allowed(
    db: Session,
    identifier: str,
    request: Request,
) -> bool:
    normalized_identifier = identifier.strip().lower()
    now = _now_utc()
    user = db.query(User).filter(User.email == normalized_identifier).first()

    if user is not None:
        cutoff = now - timedelta(seconds=PASSWORD_RESET_RATE_LIMIT_SECONDS)
        recent_count = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= cutoff,
            )
            .count()
        )
        return recent_count < PASSWORD_RESET_MAX_REQUESTS

    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{normalized_identifier}"
    attempts = _unknown_reset_attempts.get(key)
    if attempts is None:
        if len(_unknown_reset_attempts) >= _MAX_UNKNOWN_RESET_KEYS:
            _unknown_reset_attempts.popitem(last=False)
        attempts = deque()
        _unknown_reset_attempts[key] = attempts
    else:
        _unknown_reset_attempts.move_to_end(key)

    _prune_reset_attempts(attempts, now)
    if len(attempts) >= PASSWORD_RESET_MAX_REQUESTS:
        return False
    attempts.append(now)
    return True


def create_password_reset_token(db: Session, user: User) -> str:
    now = _now_utc()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update(
        {PasswordResetToken.used_at: now},
        synchronize_session=False,
    )
    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_secret(token),
        expires_at=now + timedelta(seconds=PASSWORD_RESET_TOKEN_TTL_SECONDS),
    )
    db.add(reset_token)
    db.commit()
    return token


def resolve_reset_token(db: Session, token: str) -> PasswordResetToken | None:
    if not token:
        return None
    return (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == _hash_secret(token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > _now_utc(),
        )
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
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )
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
                .filter(
                    UserSession.token_hash == _hash_secret(token),
                    UserSession.revoked_at.is_(None),
                )
                .first()
            )
            if session is None:
                return redirect_to_login(request)
            if (
                _to_utc(session.expires_at) is None
                or _to_utc(session.expires_at) <= _now_utc()
            ):
                return redirect_to_login(request)
            user = (
                db.query(User)
                .filter(User.id == session.user_id, User.status == "active")
                .first()
            )
            if user is None:
                return redirect_to_login(request)
        finally:
            db.close()
    return await call_next(request)
