"""FastAPI application composition for Gym Management."""

from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import get_authenticated_user
from app.core.config import SESSION_COOKIE_NAME
from app.core.database import SessionLocal
from app.routes import auth, dashboard, members, payments, settings


def create_app() -> FastAPI:
    app = FastAPI(title="Gym Management System")
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(members.router)
    app.include_router(payments.router)
    app.include_router(settings.router)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        public_paths = {"/", "/login", "/logout",
                        "/docs", "/openapi.json", "/redoc"}
        if request.url.path in public_paths:
            return await call_next(request)

        protected_prefixes = (
            "/dashboard",
            "/members",
            "/payments",
            "/gym-settings",
            "/account",
        )
        if not request.url.path.startswith(protected_prefixes):
            return await call_next(request)

        db = SessionLocal()
        try:
            try:
                get_authenticated_user(request, db)
            except HTTPException:
                next_path = request.url.path
                if request.url.query:
                    next_path = f"{next_path}?{request.url.query}"
                return RedirectResponse(
                    url=f"/login?next={quote(next_path, safe='')}",
                    status_code=307,
                )
        finally:
            db.close()

        return await call_next(request)

    @app.get("/")
    def home():
        return RedirectResponse(url="/dashboard", status_code=303)

    return app


app = create_app()
