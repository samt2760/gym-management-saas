from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth import get_authenticated_user
from app.core.config import (
    ENVIRONMENT,
    SESSION_COOKIE_SAME_SITE,
    SESSION_COOKIE_SECURE,
)
from app.core.database import SessionLocal
from app.routes import auth, dashboard, members, payments, settings
from app.web import (
    CSRF_COOKIE_NAME,
    create_csrf_token,
    verify_csrf_token,
)

logger = logging.getLogger(__name__)


def _get_allowed_hosts() -> list[str]:
    """
    Return the hostnames accepted by the application.

    The default includes the local development/test hosts.
    Production deployments should set ALLOWED_HOSTS explicitly.
    """
    configured_hosts = os.getenv("ALLOWED_HOSTS")

    if configured_hosts is not None:
        hosts = [host.strip() for host in configured_hosts.split(",")]
        if not any(not host for host in hosts) and not any(
            "*" in host or "://" in host or "/" in host for host in hosts
        ):
            return hosts
        if ENVIRONMENT == "production":
            raise RuntimeError("ALLOWED_HOSTS contains an invalid production host.")

    if ENVIRONMENT == "production":
        raise RuntimeError(
            "ALLOWED_HOSTS must be configured in production."
        )

    return [
        "localhost",
        "127.0.0.1",
        "testserver",
    ]


def _apply_security_headers(response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'; connect-src 'self'; "
        "img-src 'self' data:; font-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'"
    )
    # Dynamic HTML and credential workflows must not be retained by browser
    # history or intermediary caches. Static paths intentionally keep their
    # normal cache behavior.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    if ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gym Management System"
    )

    # ---------------------------------------------------------
    # Trusted host protection
    # ---------------------------------------------------------

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_get_allowed_hosts(),
    )

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(members.router)
    app.include_router(payments.router)
    app.include_router(settings.router)

    @app.middleware("http")
    async def security_middleware(
        request: Request,
        call_next,
    ):
        csrf_cookie = request.cookies.get(
            CSRF_COOKIE_NAME
        )

        if csrf_cookie is None:
            csrf_cookie = create_csrf_token()

        request.state.csrf_token = csrf_cookie

        # ---------------------------------------------------------
        # Authentication gate for protected routes
        # ---------------------------------------------------------

        protected_prefixes = (
            "/dashboard",
            "/members",
            "/payments",
            "/gym-settings",
            "/account",
        )

        public_password_paths = {
            "/account/password/forgot",
            "/account/password/reset",
            "/account/password/reset-request",
        }
        is_protected_path = (
            request.url.path.startswith(protected_prefixes)
            and request.url.path not in public_password_paths
        )

        if is_protected_path:
            db = SessionLocal()

            try:
                try:
                    get_authenticated_user(
                        request,
                        db,
                    )

                except HTTPException:
                    next_path = request.url.path

                    if request.url.query:
                        next_path = (
                            f"{next_path}?{request.url.query}"
                        )

                    response = RedirectResponse(
                        url=(
                            "/login?next="
                            f"{quote(next_path, safe='')}"
                        ),
                        status_code=307,
                    )

                    response.set_cookie(
                        key=CSRF_COOKIE_NAME,
                        value=csrf_cookie,
                        httponly=False,
                        secure=SESSION_COOKIE_SECURE,
                        samesite=SESSION_COOKIE_SAME_SITE,
                        max_age=60 * 60 * 8,
                        path="/",
                    )
                    _apply_security_headers(response)
                    return response

            finally:
                db.close()

        # ---------------------------------------------------------
        # CSRF protection
        #
        # Do NOT call request.form() here.
        #
        # We read the raw body, validate csrf_token, then replay
        # the body so FastAPI can parse Form(...) normally.
        # ---------------------------------------------------------
        csrf_exempt_paths: set[str] = set()

        if (
            request.method
            in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path not in csrf_exempt_paths
        ):
            body = await request.body()

            try:
                parsed_form = parse_qs(
                    body.decode("utf-8"),
                    keep_blank_values=True,
                )
            except UnicodeDecodeError:
                parsed_form = {}

            submitted_tokens = parsed_form.get(
                "csrf_token",
                [],
            )

            submitted_token = (
                submitted_tokens[0]
                if submitted_tokens
                else None
            )

            if (
                not isinstance(
                    submitted_token,
                    str,
                )
                or not verify_csrf_token(
                    submitted_token,
                    csrf_cookie,
                )
            ):
                response = JSONResponse(
                    {
                        "detail": (
                            "Invalid or missing CSRF token."
                        )
                    },
                    status_code=403,
                )
                _apply_security_headers(response)
                return response

            # Replay the request body for FastAPI.
            async def receive():
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }

            request._receive = receive

        response = await call_next(request)

        # ---------------------------------------------------------
        # Security response headers
        # ---------------------------------------------------------

        if not request.url.path.startswith("/static/"):
            _apply_security_headers(response)

        # ---------------------------------------------------------
        # Set CSRF cookie if this is the first request
        # ---------------------------------------------------------

        if request.cookies.get(CSRF_COOKIE_NAME) is None:
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_cookie,
                httponly=False,
                secure=SESSION_COOKIE_SECURE,
                samesite=SESSION_COOKIE_SAME_SITE,
                max_age=60 * 60 * 8,
                path="/",
            )

        return response

    @app.get("/health")
    def health_check():
        from sqlalchemy import text

        from app.core.database import engine

        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))

            return {
                "status": "ok",
                "database": "ok",
            }

        except Exception:
            logger.exception("Health check database failure")

            return JSONResponse(
                {
                    "status": "error",
                    "database": "unavailable",
                },
                status_code=503,
            )

    @app.get("/")
    def home():
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

    return app


app = create_app()
