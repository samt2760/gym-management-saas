from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_permission
from app.models import Gym, Member, Payment, User
from app.services.audit_service import record_audit
from app.services.membership_service import (
    MembershipService,
    registration_due_date,
    update_member_status,
)
from app.web import get_db, templates

router = APIRouter()


@router.get("/register")
def register_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    gym = db.query(Gym).filter(
        Gym.id == user.gym_id
    ).first()

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"gym": gym, "current_user": user},
    )


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
    gym = db.query(Gym).filter(
        Gym.id == user.gym_id
    ).first()

    if gym is None:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    try:
        MembershipService.validate_pricing(gym)
    except ValueError:
        return {
            "error": "Gym pricing is not configured correctly."
        }

    due_date = registration_due_date(
        registration_date
    )

    member = Member(
        gym_id=gym.id,
        full_name=full_name.strip(),
        phone=phone.strip(),
        email=email.strip() or None,
        date_of_birth=date_of_birth,
        registration_date=registration_date,
        membership_type="Monthly",
        payment_due_date=due_date,
        status=(
            "Active"
            if due_date >= datetime.now(UTC).date()
            else "Expired"
        ),
    )

    try:
        db.add(member)
        db.flush()

        member, registration = MembershipService.register_member(
            gym,
            member,
            registration_date=registration_date,
        )

        db.add(registration)
        record_audit(
            db, gym_id=gym.id, actor=user, action="member.created",
            resource_type="member", resource_id=member.id,
            details={"source": "registration"},
        )
        db.flush()
        record_audit(
            db, gym_id=gym.id, actor=user, action="payment.created",
            resource_type="payment", resource_id=registration.id,
            details={"payment_type": "Registration", "amount_minor": registration.amount},
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


@router.get("/members")
def members_page(
    request: Request,
    search: str = "",
    status: str = "all",
    sort: str = "expiry_soonest",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.view")),
):
    update_member_status(db, user.gym_id)

    today = datetime.now(UTC).date()
    status = status if status in {"all", "active", "expired", "due_soon"} else "all"
    sort = sort if sort in {
        "expiry_soonest",
        "expiry_latest",
        "name_asc",
        "name_desc",
        "registration_newest",
        "registration_oldest",
    } else "expiry_soonest"

    base_filter = (
        Member.gym_id == user.gym_id,
        Member.deleted_at.is_(None),
    )

    total_members = db.query(Member).filter(*base_filter).count()
    active_count = db.query(Member).filter(
        *base_filter,
        Member.payment_due_date >= today,
    ).count()
    expired_count = db.query(Member).filter(
        *base_filter,
        Member.payment_due_date < today,
    ).count()
    due_soon_count = db.query(Member).filter(
        *base_filter,
        Member.payment_due_date >= today,
        Member.payment_due_date <= today + timedelta(days=7),
    ).count()

    query = db.query(Member).filter(*base_filter)

    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            Member.full_name.ilike(term) | Member.phone.ilike(term)
        )

    if status == "active":
        query = query.filter(Member.payment_due_date >= today)
    elif status == "expired":
        query = query.filter(Member.payment_due_date < today)
    elif status == "due_soon":
        query = query.filter(
            Member.payment_due_date >= today,
            Member.payment_due_date <= today + timedelta(days=7),
        )

    order_by = {
        "expiry_latest": Member.payment_due_date.desc(),
        "name_asc": Member.full_name.asc(),
        "name_desc": Member.full_name.desc(),
        "registration_newest": Member.registration_date.desc(),
        "registration_oldest": Member.registration_date.asc(),
    }.get(sort, Member.payment_due_date.asc())
    members = query.order_by(order_by, Member.id.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="members.html",
        context={
            "members": members,
            "search": search,
            "status": status,
            "sort": sort,
            "total_members": total_members,
            "active_count": active_count,
            "expired_count": expired_count,
            "due_soon_count": due_soon_count,
            "today": today,
                "current_user": user,
        },
    )


@router.get("/members/existing")
def existing_member_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.create")),
):
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    return templates.TemplateResponse(
        request=request,
        name="existing_member.html",
        context={"gym": gym, "current_user": user},
    )


@router.post("/members/existing")
def create_existing_member(
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    payment_due_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.create")),
):
    today = datetime.now(UTC).date()
    full_name = full_name.strip()
    phone = phone.strip()
    email = email.strip() or None

    if not full_name or not phone:
        raise HTTPException(status_code=400, detail="Name and phone are required.")
    if registration_date > today:
        raise HTTPException(
            status_code=400,
            detail="Registration date cannot be in the future.",
        )
    if payment_due_date < registration_date:
        raise HTTPException(
            status_code=400,
            detail="Payment due date cannot be before registration date.",
        )
    if date_of_birth is not None and date_of_birth > today:
        raise HTTPException(
            status_code=400,
            detail="Date of birth cannot be in the future.",
        )
    if date_of_birth is not None and date_of_birth > registration_date:
        raise HTTPException(
            status_code=400,
            detail="Date of birth cannot be after registration date.",
        )

    duplicate = db.query(Member).filter(
        Member.gym_id == user.gym_id,
        Member.deleted_at.is_(None),
        Member.full_name.ilike(full_name),
    ).first()
    if duplicate is not None:
        raise HTTPException(
            status_code=400,
            detail="An active member with this name already exists.",
        )

    member = Member(
        gym_id=user.gym_id,
        full_name=full_name,
        phone=phone,
        email=email,
        date_of_birth=date_of_birth,
        registration_date=registration_date,
        membership_type="Monthly",
        payment_due_date=payment_due_date,
        status="Active" if payment_due_date >= today else "Expired",
    )
    db.add(member)
    db.flush()
    record_audit(
        db, gym_id=user.gym_id, actor=user, action="member.created",
        resource_type="member", resource_id=member.id,
        details={"source": "existing_member"},
    )
    db.commit()
    db.refresh(member)

    return RedirectResponse(url=f"/members/{member.id}", status_code=303)


@router.get("/members/deleted")
def deleted_members_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.view")),
):
    gym = db.query(Gym).filter(Gym.id == user.gym_id).first()
    deleted_members = db.query(Member).filter(
        Member.gym_id == user.gym_id,
        Member.deleted_at.is_not(None),
    ).order_by(Member.deleted_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="deleted_members.html",
        context={
            "deleted_members": deleted_members,
            "gym": gym,
            "current_user": user,
        },
    )


@router.post("/members/{member_id}/restore")
def restore_member(
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.delete")),
):
    member = db.query(Member).filter(
        Member.id == member_id, Member.gym_id == user.gym_id
    ).first()
    if member is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    if member.deleted_at is None:
        raise HTTPException(status_code=404, detail="Deleted member not found.")

    member.deleted_at = None
    member.status = (
        "Active"
        if member.payment_due_date >= datetime.now(UTC).date()
        else "Expired"
    )
    record_audit(
        db, gym_id=user.gym_id, actor=user, action="member.restored",
        resource_type="member", resource_id=member.id,
    )
    db.commit()
    return RedirectResponse(url="/members", status_code=303)


@router.get("/members/{member_id}")
def member_details(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.view")),
):
    update_member_status(db, user.gym_id)

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == user.gym_id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    gym = db.query(Gym).filter(
        Gym.id == user.gym_id
    ).first()

    payments = (
        db.query(Payment)
        .filter(
            Payment.gym_id == user.gym_id,
            Payment.member_id == member.id,
        )
        .order_by(
            Payment.payment_date.desc(),
            Payment.id.desc(),
        )
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="member_details.html",
        context={
            "member": member,
            "payments": payments,
            "membership_fee": gym.monthly_fee,
            "renewal_idempotency_key": str(uuid4()),
            "gym": gym,
            "current_user": user,
        },
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
        .filter(
            Member.id == member_id,
            Member.gym_id == user.gym_id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    return templates.TemplateResponse(
        request=request,
        name="edit_member.html",
        context={"member": member, "current_user": user},
    )


@router.post("/members/{member_id}/edit")
def update_member(
    member_id: int,
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.edit")),
):
    """
    Update member profile information only.

    IMPORTANT:
    payment_due_date is intentionally NOT accepted here.

    Membership entitlement must only be changed through controlled
    membership operations such as registration and renewal.
    """

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == user.gym_id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    member.full_name = full_name.strip()
    member.phone = phone.strip()
    member.email = email.strip() or None
    member.date_of_birth = date_of_birth
    member.registration_date = registration_date
    member.membership_type = "Monthly"

    # Do NOT modify payment_due_date here.
    #
    # The existing entitlement remains intact.
    # Recalculate only the display/status state from the
    # existing entitlement date.
    member.status = (
        "Active"
        if member.payment_due_date >= datetime.now(UTC).date()
        else "Expired"
    )

    record_audit(
        db, gym_id=user.gym_id, actor=user, action="member.updated",
        resource_type="member", resource_id=member.id,
    )
    db.commit()

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


@router.post("/members/{member_id}/delete")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("members.delete")),
):
    member = db.query(Member).filter(
        Member.id == member_id, Member.gym_id == user.gym_id
    ).first()
    if member is None:
        raise HTTPException(status_code=403, detail="Access denied.")
    if member.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Member not found.")

    member.deleted_at = datetime.now(UTC)
    record_audit(
        db, gym_id=user.gym_id, actor=user, action="member.deleted",
        resource_type="member", resource_id=member.id,
    )
    db.commit()

    return RedirectResponse(
        url="/members",
        status_code=303,
    )


@router.post("/members/{member_id}/renew")
def renew_membership(
    member_id: int,
    amount: int = Form(...),
    idempotency_key: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("payments.create")),
):
    key = (idempotency_key or "").strip() or str(uuid4())
    if len(key) > 128:
        raise HTTPException(status_code=400, detail="Invalid idempotency key.")

    try:
        MembershipService.renew_membership_transaction(
            db,
            gym_id=user.gym_id,
            member_id=member_id,
            amount=amount,
            idempotency_key=key,
            payment_date=datetime.now(UTC).date(),
            actor=user,
        )

    except ValueError as exc:
        return {"error": str(exc)}

    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied.")

    return RedirectResponse(
        url=f"/members/{member_id}",
        status_code=303,
    )
