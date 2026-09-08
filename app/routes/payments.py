from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import get_current_gym, require_permission
from app.models import Payment, User
from app.services.reporting_service import payment_totals
from app.web import get_db, templates

router = APIRouter()


@router.get("/payments")
def payments_page(
    request: Request,
    period: str = "all",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("payments.view")),
):
    gym = get_current_gym(db, user)
    today = datetime.now(UTC).date()
    all_payments = db.query(Payment).filter(Payment.gym_id == user.gym_id).order_by(
        Payment.payment_date.desc(), Payment.id.desc()).all()
    if period == "today":
        payments = [
            payment for payment in all_payments if payment.payment_date == today]
    elif period == "month":
        payments = [
            payment
            for payment in all_payments
            if payment.payment_date.year == today.year and payment.payment_date.month == today.month
        ]
    else:
        period = "all"
        payments = all_payments

    total_revenue, today_revenue, month_revenue = payment_totals(
        all_payments, today)
    payment_groups: dict[str, dict[str, list[Payment] | int]] = {}
    for payment in payments:
        month_key = payment.payment_date.strftime("%B %Y")
        if month_key not in payment_groups:
            payment_groups[month_key] = {"payments": [], "total": 0}
        payment_groups[month_key]["payments"].append(
            payment)  # type: ignore[union-attr]
        # type: ignore[operator]
        if payment.status == "Completed":
            payment_groups[month_key]["total"] += payment.amount

    return templates.TemplateResponse(
        request=request,
        name="payments.html",
        context={
            "gym": gym,
            "payment_groups": payment_groups,
            "total_revenue": total_revenue,
            "today_revenue": today_revenue,
            "month_revenue": month_revenue,
            "period": period,
                "current_user": user,
        },
    )
