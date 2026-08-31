from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from database import engine, get_db
from models import Base, Gym, Member, Payment


app = FastAPI(title="Gym Management System")

templates = Jinja2Templates(directory="templates")


# ============================================================
# DATABASE
# ============================================================

Base.metadata.create_all(bind=engine)


# ============================================================
# GYM
# ============================================================

def get_or_create_gym(db: Session) -> Gym:
    gym = (
        db.query(Gym)
        .order_by(Gym.id.asc())
        .first()
    )

    if gym is None:
        now = datetime.utcnow()

        gym = Gym(
            name="My Gym",
            currency="GHS",
            registration_fee=0,
            monthly_fee=0,
            created_at=now,
            updated_at=now,
        )

        db.add(gym)
        db.commit()
        db.refresh(gym)

    return gym


# ============================================================
# MEMBER STATUS
# ============================================================

def update_member_status(db: Session) -> None:
    today = date.today()

    members = (
        db.query(Member)
        .filter(Member.deleted_at.is_(None))
        .all()
    )

    changed = False

    for member in members:

        if member.payment_due_date >= today:
            new_status = "Active"
        else:
            new_status = "Expired"

        if member.status != new_status:
            member.status = new_status
            member.updated_at = datetime.utcnow()
            changed = True

    if changed:
        db.commit()


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    return RedirectResponse(
        url="/dashboard",
        status_code=303,
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
):
    today = date.today()

    gym = get_or_create_gym(db)

    update_member_status(db)

    # --------------------------------------------------------
    # MEMBERS
    # --------------------------------------------------------

    total_members = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .count()
    )

    active_members = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
            Member.payment_due_date >= today,
        )
        .count()
    )

    expired_members = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
            Member.payment_due_date < today,
        )
        .count()
    )

    # --------------------------------------------------------
    # DUE WITHIN 7 DAYS
    # --------------------------------------------------------

    due_soon_members = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
            Member.payment_due_date >= today,
            Member.payment_due_date <= today + timedelta(days=7),
        )
        .order_by(Member.payment_due_date.asc())
        .all()
    )

    # --------------------------------------------------------
    # PAYMENTS
    # --------------------------------------------------------

    all_payments = (
        db.query(Payment)
        .filter(Payment.gym_id == gym.id)
        .order_by(
            Payment.payment_date.desc(),
            Payment.id.desc(),)
        .all()
    )

    total_collected = sum(
        payment.amount
        for payment in all_payments
    )

    today_revenue = sum(
        payment.amount
        for payment in all_payments
        if payment.payment_date == today
    )

    month_revenue = sum(
        payment.amount
        for payment in all_payments
        if (
            payment.payment_date.year == today.year
            and payment.payment_date.month == today.month
        )
    )

    # --------------------------------------------------------
    # RECENT MEMBERS
    # --------------------------------------------------------

    recent_members = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .order_by(Member.id.desc())
        .limit(5)
        .all()
    )

    # --------------------------------------------------------
    # PAGE
    # --------------------------------------------------------

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "gym": gym,
            "total_members": total_members,
            "active_members": active_members,
            "expired_members": expired_members,
            "due_soon_members": due_soon_members,
            "members_due_soon": due_soon_members,
            "total_collected": total_collected,
            "today_revenue": today_revenue,
            "month_revenue": month_revenue,
            "recent_members": recent_members,
        },
    )


# ============================================================
# MEMBERS
# ============================================================

@app.get("/members")
def members_page(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db),
):
    update_member_status(db)

    gym = get_or_create_gym(db)

    query = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
    )

    if search.strip():

        search_term = f"%{search.strip()}%"

        query = query.filter(
            Member.full_name.ilike(search_term)
            | Member.phone.ilike(search_term)
        )

    members = (
        query
        .order_by(Member.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="members.html",
        context={
            "members": members,
            "search": search,
            "gym": gym,
        },
    )


# ============================================================
# REGISTER PAGE
# ============================================================

@app.get("/register")
def register_page(
    request: Request,
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={
            "gym": gym,
        },
    )


# ============================================================
# REGISTER MEMBER
# ============================================================

@app.post("/members")
def create_member(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    name = full_name.strip()
    phone_number = phone.strip()

    if not name:
        return {
            "error": "Full name is required."
        }

    if not phone_number:
        return {
            "error": "Phone number is required."
        }

    if gym.monthly_fee <= 0:
        return {
            "error": (
                "Monthly membership fee is not configured. "
                "Configure it in Gym Settings first."
            )
        }

    # ============================================================
# ADD EXISTING MEMBER PAGE
# ============================================================


@app.get("/members/existing")
def existing_member_page(
    request: Request,
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    return templates.TemplateResponse(
        request=request,
        name="existing_member.html",
        context={
            "gym": gym,
        },
    )

    # ============================================================
# ADD EXISTING MEMBER
# ============================================================


@app.post("/members/existing")
def create_existing_member(
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    payment_due_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    name = full_name.strip()
    phone_number = phone.strip()

    if not name:
        return {
            "error": "Full name is required."
        }

    if not phone_number:
        return {
            "error": "Phone number is required."
        }

    if payment_due_date < registration_date:
        return {
            "error": (
                "Payment due date cannot be earlier "
                "than the registration date."
            )
        }

    # --------------------------------------------------------
    # DUPLICATE NAME CHECK
    # --------------------------------------------------------

    duplicate = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
            Member.full_name.ilike(name),
        )
        .first()
    )

    if duplicate:
        return {
            "error": (
                f"A member named '{name}' already exists."
            )
        }

    # --------------------------------------------------------
    # CREATE EXISTING MEMBER
    # --------------------------------------------------------

    now = datetime.utcnow()

    member = Member(
        gym_id=gym.id,
        full_name=name,
        phone=phone_number,
        email=email.strip() or None,
        date_of_birth=date_of_birth,
        registration_date=registration_date,
        membership_type="Monthly",
        payment_due_date=payment_due_date,
        status=(
            "Active"
            if payment_due_date >= date.today()
            else "Expired"
        ),
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )

    db.add(member)
    db.commit()
    db.refresh(member)

    # IMPORTANT:
    # No registration payment is created.
    # This member already existed before the system.

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )

    # --------------------------------------------------------
    # DUPLICATE NAME CHECK
    # --------------------------------------------------------

    duplicate = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
            Member.full_name.ilike(name),
        )
        .first()
    )

    if duplicate:
        return {
            "error": (
                f"A member named '{name}' already exists."
            )
        }

    # --------------------------------------------------------
    # CREATE MEMBER
    # --------------------------------------------------------

    now = datetime.utcnow()

    member = Member(
        gym_id=gym.id,
        full_name=name,
        phone=phone_number,
        email=email.strip() or None,
        date_of_birth=date_of_birth,
        registration_date=registration_date,
        membership_type="Monthly",
        payment_due_date=(
            registration_date
            + relativedelta(months=1)
        ),
        status="Active",
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )

    db.add(member)
    db.flush()

    # --------------------------------------------------------
    # REGISTRATION PAYMENT
    #
    # Registration payment records the registration fee.
    # The first month is represented by the member's
    # one-month payment_due_date.
    # --------------------------------------------------------

    if gym.registration_fee > 0:

        payment = Payment(
            gym_id=gym.id,
            member_id=member.id,
            member_name=member.full_name,
            amount=gym.registration_fee,
            currency=gym.currency,
            payment_date=registration_date,
            membership_type="Monthly",
            payment_type="Registration",
            created_at=now,
            updated_at=now,
        )

        db.add(payment)

    db.commit()
    db.refresh(member)

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


# ============================================================
# MEMBER DETAILS
# ============================================================

@app.get("/members/{member_id}")
def member_details(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    update_member_status(db)

    gym = get_or_create_gym(db)

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        return {
            "error": "Member not found."
        }

    payments = (
        db.query(Payment)
        .filter(
            Payment.member_id == member.id,
            Payment.gym_id == gym.id,
        )
        .order_by(
            Payment.payment_date.desc(),
            Payment.id.desc(),
        )
        .all()
    )

    membership_fee = gym.monthly_fee

    return templates.TemplateResponse(
        request=request,
        name="member_details.html",
        context={
            "member": member,
            "payments": payments,
            "gym": gym,
            "membership_fee": membership_fee,
        },
    )


# ============================================================
# EDIT MEMBER PAGE
# ============================================================

@app.get("/members/{member_id}/edit")
def edit_member_page(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        return {
            "error": "Member not found."
        }

    return templates.TemplateResponse(
        request=request,
        name="edit_member.html",
        context={
            "member": member,
            "gym": gym,
        },
    )


# ============================================================
# UPDATE MEMBER
# ============================================================

@app.post("/members/{member_id}/edit")
def update_member(
    member_id: int,
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    payment_due_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        return {
            "error": "Member not found."
        }

    name = full_name.strip()

    # --------------------------------------------------------
    # DUPLICATE NAME CHECK
    # --------------------------------------------------------

    duplicate = (
        db.query(Member)
        .filter(
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
            Member.full_name.ilike(name),
            Member.id != member.id,
        )
        .first()
    )

    if duplicate:
        return {
            "error": (
                f"A member named '{name}' already exists."
            )
        }

    member.full_name = name
    member.phone = phone.strip()
    member.email = email.strip() or None
    member.date_of_birth = date_of_birth
    member.registration_date = registration_date
    member.membership_type = "Monthly"
    member.payment_due_date = payment_due_date

    member.status = (
        "Active"
        if payment_due_date >= date.today()
        else "Expired"
    )

    member.updated_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


# ============================================================
# DELETE MEMBER
# ============================================================

@app.post("/members/{member_id}/delete")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        return {
            "error": "Member not found."
        }

    # Preserve payment history.
    payments = (
        db.query(Payment)
        .filter(
            Payment.member_id == member.id,
            Payment.gym_id == gym.id,
        )
        .all()
    )

    for payment in payments:
        payment.member_id = None

    db.delete(member)
    db.commit()

    return RedirectResponse(
        url="/members",
        status_code=303,
    )


# ============================================================
# RENEW MEMBERSHIP
# ============================================================

@app.post("/members/{member_id}/renew")
def renew_membership(
    member_id: int,
    amount: int = Form(...),
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    member = (
        db.query(Member)
        .filter(
            Member.id == member_id,
            Member.gym_id == gym.id,
            Member.deleted_at.is_(None),
        )
        .first()
    )

    if member is None:
        return {
            "error": "Member not found."
        }

    fee = gym.monthly_fee

    if fee <= 0:
        return {
            "error": (
                "Monthly renewal fee is not configured."
            )
        }

    if amount <= 0 or amount % fee != 0:
        return {
            "error": (
                f"Invalid payment amount. "
                f"Enter a multiple of {fee}."
            )
        }

    months_paid = amount // fee

    today = date.today()

    if member.payment_due_date < today:
        start_date = today
    else:
        start_date = member.payment_due_date

    member.payment_due_date = (
        start_date
        + relativedelta(months=months_paid)
    )

    member.status = "Active"
    member.updated_at = datetime.utcnow()

    payment = Payment(
        gym_id=gym.id,
        member_id=member.id,
        member_name=member.full_name,
        amount=amount,
        currency=gym.currency,
        payment_date=today,
        membership_type="Monthly",
        payment_type="Renewal",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(payment)
    db.commit()

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


# ============================================================
# PAYMENTS
# ============================================================

@app.get("/payments")
def payments_page(
    request: Request,
    period: str = "all",
    db: Session = Depends(get_db),
):
    today = date.today()

    gym = get_or_create_gym(db)

    # Get payments belonging only to this gym
    all_payments = (
        db.query(Payment)
        .filter(Payment.gym_id == gym.id)
        .order_by(
            Payment.payment_date.desc(),
            Payment.id.desc(),
        )
        .all()
    )

    # Filter displayed payments
    if period == "today":
        payments = [
            payment
            for payment in all_payments
            if payment.payment_date == today
        ]

    elif period == "month":
        payments = [
            payment
            for payment in all_payments
            if (
                payment.payment_date.year == today.year
                and payment.payment_date.month == today.month
            )
        ]

    else:
        period = "all"
        payments = all_payments

    # Revenue totals
    total_revenue = sum(
        payment.amount
        for payment in all_payments
    )

    today_revenue = sum(
        payment.amount
        for payment in all_payments
        if payment.payment_date == today
    )

    month_revenue = sum(
        payment.amount
        for payment in all_payments
        if (
            payment.payment_date.year == today.year
            and payment.payment_date.month == today.month
        )
    )

    # Group displayed payments by month
    payment_groups = {}

    for payment in payments:

        month_key = payment.payment_date.strftime("%B %Y")

        if month_key not in payment_groups:
            payment_groups[month_key] = {
                "payments": [],
                "total": 0,
            }

        payment_groups[month_key]["payments"].append(payment)

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
        },
    )
# ============================================================
# GYM SETTINGS
# ============================================================


@app.get("/gym-settings")
def gym_settings(
    request: Request,
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    return templates.TemplateResponse(
        request=request,
        name="gym_settings.html",
        context={
            "gym": gym,
        },
    )


# ============================================================
# UPDATE GYM SETTINGS
# ============================================================

@app.post("/gym-settings")
def update_gym_settings(
    name: str = Form(...),
    currency: str = Form(...),
    registration_fee: int = Form(...),
    monthly_fee: int = Form(...),
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    if registration_fee < 0:
        return {
            "error": "Registration fee cannot be negative."
        }

    if monthly_fee <= 0:
        return {
            "error": (
                "Monthly renewal fee must be greater than zero."
            )
        }

    gym.name = name.strip() or "My Gym"
    gym.currency = currency.strip().upper() or "GHS"
    gym.registration_fee = registration_fee
    gym.monthly_fee = monthly_fee
    gym.updated_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(
        url="/gym-settings",
        status_code=303,
    )
