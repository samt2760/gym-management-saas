"""Configuration shared by database consumers, not web-session consumers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# This preserves local-development convenience while keeping operational tools
# independent of the web application's session-secret validation.
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gym.db")

DATABASE_CONNECT_TIMEOUT_SECONDS = int(
    os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10")
)
