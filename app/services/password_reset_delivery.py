from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

from app.core.config import ENVIRONMENT


@dataclass(frozen=True)
class PasswordResetMessage:
    recipient: str
    reset_url: str


class PasswordResetDelivery(Protocol):
    def deliver(self, message: PasswordResetMessage) -> None:
        """Deliver a password-reset message without logging its contents."""


class NullPasswordResetDelivery:
    def deliver(self, message: PasswordResetMessage) -> None:
        return None


class InMemoryPasswordResetDelivery:
    def __init__(self, max_messages: int = 100) -> None:
        self.messages: deque[PasswordResetMessage] = deque(maxlen=max_messages)

    def deliver(self, message: PasswordResetMessage) -> None:
        self.messages.append(message)

    def clear(self) -> None:
        self.messages.clear()


development_delivery = InMemoryPasswordResetDelivery()
_production_delivery = NullPasswordResetDelivery()


def get_password_reset_delivery() -> PasswordResetDelivery:
    if ENVIRONMENT == "production":
        return _production_delivery
    return development_delivery
