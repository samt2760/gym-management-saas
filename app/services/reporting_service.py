"""Read-model helpers for the current dashboard and payment screens."""

from __future__ import annotations

from datetime import date

from app.models import Payment


def payment_totals(payments: list[Payment], today: date) -> tuple[int, int, int]:
    total = sum(payment.amount for payment in payments)
    today_total = sum(payment.amount for payment in payments if payment.payment_date == today)
    month_total = sum(
        payment.amount
        for payment in payments
        if payment.payment_date.year == today.year and payment.payment_date.month == today.month
    )
    return total, today_total, month_total
