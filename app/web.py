"""Shared web dependencies for server-rendered routes."""

from collections.abc import Generator

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIRECTORY
from app.core.database import SessionLocal


templates = Jinja2Templates(directory=str(TEMPLATES_DIRECTORY))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
