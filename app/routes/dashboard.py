from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.models import Gym, Member, Payment, User
from app.services.membership_service import get_or_create_gym, update_member_status
from app.services.reporting_service import payment_totals
from app.web import get_db, templates


router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    today = date.today()
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    update_member_status(db)

    active_member_filter = Member.deleted_at.is_(None)
    total_members = db.query(Member).filter(Member.gym_id == user.gym_id, active_member_filter).count()
    active_members = (
        db.query(Member)
        .filter(Member.gym_id == user.gym_id, active_member_filter, Member.payment_due_date >= today)
        .count()
    )
    expired_members = (
        db.query(Member)
        .filter(Member.gym_id == user.gym_id, active_member_filter, Member.payment_due_date < today)
        .count()
    )
    due_soon_members = (
        db.query(Member)
        .filter(
            Member.gym_id == user.gym_id,
            active_member_filter,
            Member.payment_due_date >= today,
            Member.payment_due_date <= today + timedelta(days=7),
        )
        .order_by(Member.payment_due_date.asc())
        .all()
    )
    all_payments = db.query(Payment).filter(Payment.gym_id == user.gym_id).order_by(
        Payment.payment_date.desc(), Payment.id.desc()).all()
    total_collected, today_revenue, month_revenue = payment_totals(
        all_payments, today)
    recent_members = (
        db.query(Member)
        .filter(Member.gym_id == user.gym_id, active_member_filter)
        .order_by(Member.id.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "gym": gym,
            "total_members": total_members,
            "active_members": active_members,
            "expired_members": expired_members,
            "members_due_soon": len(due_soon_members),
            "due_soon_members": due_soon_members,
            "recent_members": recent_members,
            "total_collected": total_collected,
            "today_revenue": today_revenue,
            "month_revenue": month_revenue,
        },
    )
