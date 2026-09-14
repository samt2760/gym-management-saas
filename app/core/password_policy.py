"""Password-policy configuration shared by web and bootstrap workflows."""

from __future__ import annotations

import os

PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "12"))
