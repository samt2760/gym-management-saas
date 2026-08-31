from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.auth import get_tenant_object, require_auth, require_permission
from app.models import Gym, Member, Payment, User
from app.services.membership_service import (
    MembershipService,
    extend_membership,
    get_or_create_gym,
    registration_due_date,
    update_member_status,
)
from app.services.payment_service import registration_payment, renewal_payment
from app.models.mixins import utc_now
from app.web import get_db, templates


router = APIRouter()


@router.get("/register")
def register_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    return templates.TemplateResponse(request=request, name="register.html", context={"gym": gym})


@router.post("/members")
def create_member(
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.create")),
):
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    if gym is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    try:
        MembershipService.validate_pricing(gym)
    except ValueError:
        return {"error": "Gym pricing is not configured correctly."}

    member = Member(
        gym_id=gym.id,
        full_name=full_name.strip(),
        phone=phone.strip(),
        email=email.strip() or None,
        date_of_birth=date_of_birth,
        registration_date=registration_date,
        membership_type="Monthly",
        payment_due_date=registration_due_date(registration_date),
        status="Active" if registration_due_date(registration_date) >= date.today() else "Expired",
    )

    db.add(member)
    db.commit()
    db.refresh(member)

    member, registration = MembershipService.register_member(gym, member, registration_date=registration_date)
    db.add(registration)
    db.commit()
    return RedirectResponse(url=f"/members/{member.id}", status_code=303)


@router.get("/members")
def members_page(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.view")),
):
    update_member_status(db)
    if search.strip():
        term = f"%{search.strip()}%"
        members = (
            db.query(Member)
            .filter(
                Member.gym_id == user.gym_id,
                Member.deleted_at.is_(None),
                Member.full_name.ilike(term) | Member.phone.ilike(term),
            )
            .order_by(Member.id.desc())
            .all()
        )
    else:
        members = (
            db.query(Member)
            .filter(Member.gym_id == user.gym_id, Member.deleted_at.is_(None))
            .order_by(Member.id.desc())
            .all()
        )
    return templates.TemplateResponse(
        request=request, name="members.html", context={"members": members, "search": search}
    )


@router.get("/members/{member_id}")
def member_details(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.view")),
):
    member = (
        db.query(Member)
        .filter(Member.id == member_id, Member.gym_id == user.gym_id, Member.deleted_at.is_(None))
        .first()
    )
    if member is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    payments = (
        db.query(Payment)
        .filter(Payment.gym_id == user.gym_id, Payment.member_id == member.id)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="member_details.html",
        context={"member": member, "payments": payments,
                 "membership_fee": gym.monthly_fee, "gym": gym},
    )


@router.get("/members/{member_id}/edit")
def edit_member_page(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.edit")),
):
    member = (
        db.query(Member)
        .filter(Member.id == member_id, Member.gym_id == user.gym_id, Member.deleted_at.is_(None))
        .first()
    )
    if member is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    return templates.TemplateResponse(request=request, name="edit_member.html", context={"member": member})


@router.post("/members/{member_id}/edit")
def update_member(
    member_id: int,
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    payment_due_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.edit")),
):
    member = (
        db.query(Member)
        .filter(Member.id == member_id, Member.gym_id == user.gym_id, Member.deleted_at.is_(None))
        .first()
    )
    if member is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    member.full_name = full_name.strip()
    member.phone = phone.strip()
    member.email = email.strip() or None
    member.date_of_birth = date_of_birth
    member.registration_date = registration_date
    member.membership_type = "Monthly"
    member.payment_due_date = payment_due_date
    member.status = "Active" if payment_due_date >= date.today() else "Expired"
    db.commit()
    return RedirectResponse(url=f"/members/{member.id}", status_code=303)


@router.post("/members/{member_id}/delete")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.delete")),
):
    member = get_tenant_object(db, user, Member, member_id)
    if member is None:
        return {"error": "Member not found"}

    payments = db.query(Payment).filter(Payment.gym_id == user.gym_id, Payment.member_id == member.id).all()
    for payment in payments:
        payment.member_id = None
        payment.member_name = member.full_name

    db.delete(member)
    db.commit()
    return RedirectResponse(url="/members", status_code=303)


@router.post("/members/{member_id}/renew")
def renew_membership(
    member_id: int,
    amount: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("payments.create")),
):
    member = (
        db.query(Member)
        .filter(Member.id == member_id, Member.gym_id == user.gym_id, Member.deleted_at.is_(None))
        .first()
    )
    if member is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    try:
        payment = MembershipService.renew_membership(gym, member, amount, payment_date=date.today())
    except ValueError as exc:
        return {"error": str(exc)}

    db.add(payment)
    db.commit()
    return RedirectResponse(url=f"/members/{member_id}", status_code=303)
