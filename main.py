from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SessionLocal, engine
from models import Base, Gym, Member, Payment

app = FastAPI(title="Gym Management System")
templates = Jinja2Templates(directory="templates")

Base.metadata.create_all(bind=engine)


def migrate_database():
    # Lightweight migration support for an older prototype database.
    with engine.connect() as connection:
        gym_columns = {
            column[1]
            for column in connection.execute(text("PRAGMA table_info(gyms)")).fetchall()
        }

        if "registration_fee" not in gym_columns:
            connection.execute(
                text("ALTER TABLE gyms ADD COLUMN registration_fee INTEGER DEFAULT 0")
            )

        if "monthly_fee" not in gym_columns:
            connection.execute(
                text("ALTER TABLE gyms ADD COLUMN monthly_fee INTEGER DEFAULT 0")
            )

        payment_columns = {
            column[1]
            for column in connection.execute(text("PRAGMA table_info(payments)")).fetchall()
        }

        if "payment_type" not in payment_columns:
            connection.execute(
                text(
                    "ALTER TABLE payments "
                    "ADD COLUMN payment_type TEXT DEFAULT 'Renewal'"
                )
            )

        connection.commit()


migrate_database()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_gym(db: Session) -> Gym:
    gym = db.query(Gym).order_by(Gym.id.asc()).first()

    if gym is None:
        gym = Gym(
            name="My Gym",
            currency="GHS",
            registration_fee=0,
            monthly_fee=0,
        )
        db.add(gym)
        db.commit()
        db.refresh(gym)

    return gym


def update_member_status(db: Session):
    today = date.today()
    changed = False

    members = db.query(Member).all()

    for member in members:
        new_status = "Active" if member.payment_due_date >= today else "Expired"
        if member.status != new_status:
            member.status = new_status
            changed = True

    if changed:
        db.commit()


@app.get("/")
def home():
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    gym = get_or_create_gym(db)
    update_member_status(db)

    total_members = db.query(Member).count()
    active_members = db.query(Member).filter(Member.payment_due_date >= today).count()
    expired_members = db.query(Member).filter(Member.payment_due_date < today).count()

    due_soon_members = (
        db.query(Member)
        .filter(
            Member.payment_due_date >= today,
            Member.payment_due_date <= today + timedelta(days=7),
        )
        .order_by(Member.payment_due_date.asc())
        .all()
    )

    all_payments = (
        db.query(Payment)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )

    total_collected = sum(payment.amount for payment in all_payments)
    today_revenue = sum(
        payment.amount for payment in all_payments
        if payment.payment_date == today
    )
    month_revenue = sum(
        payment.amount for payment in all_payments
        if payment.payment_date.year == today.year
        and payment.payment_date.month == today.month
    )

    recent_members = (
        db.query(Member)
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


@app.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    gym = get_or_create_gym(db)

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"gym": gym},
    )


@app.post("/members")
def create_member(
    full_name: str = Form(...),
    phone: str = Form(...),
    registration_date: date = Form(...),
    email: str = Form(""),
    date_of_birth: date | None = Form(None),
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    if gym.registration_fee < 0 or gym.monthly_fee <= 0:
        return {"error": "Gym pricing is not configured correctly."}

    payment_due_date = registration_date + relativedelta(months=1)

    member = Member(
        full_name=full_name.strip(),
        phone=phone.strip(),
        email=email.strip() or None,
        date_of_birth=date_of_birth,
        registration_date=registration_date,
        membership_type="Monthly",
        payment_due_date=payment_due_date,
        status="Active" if payment_due_date >= date.today() else "Expired",
    )

    db.add(member)
    db.commit()
    db.refresh(member)

    payment = Payment(
        member_id=member.id,
        member_name=member.full_name,
        amount=gym.registration_fee,
        payment_date=registration_date,
        membership_type="Monthly",
        payment_type="Registration",
    )

    db.add(payment)
    db.commit()

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


@app.get("/members")
def members_page(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db),
):
    update_member_status(db)

    if search.strip():
        term = f"%{search.strip()}%"
        members = (
            db.query(Member)
            .filter(
                (Member.full_name.ilike(term))
                | (Member.phone.ilike(term))
            )
            .order_by(Member.id.desc())
            .all()
        )
    else:
        members = (
            db.query(Member)
            .order_by(Member.id.desc())
            .all()
        )

    return templates.TemplateResponse(
        request=request,
        name="members.html",
        context={
            "members": members,
            "search": search,
        },
    )


@app.get("/members/{member_id}")
def member_details(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(Member.id == member_id).first()

    if member is None:
        return {"error": "Member not found"}

    gym = get_or_create_gym(db)

    payments = (
        db.query(Payment)
        .filter(Payment.member_id == member.id)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="member_details.html",
        context={
            "member": member,
            "payments": payments,
            "membership_fee": gym.monthly_fee,
            "gym": gym,
        },
    )


@app.get("/members/{member_id}/edit")
def edit_member_page(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(Member.id == member_id).first()

    if member is None:
        return {"error": "Member not found"}

    return templates.TemplateResponse(
        request=request,
        name="edit_member.html",
        context={"member": member},
    )


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
    member = db.query(Member).filter(Member.id == member_id).first()

    if member is None:
        return {"error": "Member not found"}

    member.full_name = full_name.strip()
    member.phone = phone.strip()
    member.email = email.strip() or None
    member.date_of_birth = date_of_birth
    member.registration_date = registration_date
    member.membership_type = "Monthly"
    member.payment_due_date = payment_due_date
    member.status = "Active" if payment_due_date >= date.today() else "Expired"

    db.commit()

    return RedirectResponse(
        url=f"/members/{member.id}",
        status_code=303,
    )


@app.post("/members/{member_id}/delete")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(Member.id == member_id).first()

    if member is None:
        return {"error": "Member not found"}

    # Keep payment history even after member deletion.
    payments = db.query(Payment).filter(Payment.member_id == member.id).all()

    for payment in payments:
        payment.member_id = None

    db.delete(member)
    db.commit()

    return RedirectResponse(url="/members", status_code=303)


@app.get("/payments")
def payments_page(
    request: Request,
    period: str = "all",
    db: Session = Depends(get_db),
):
    today = date.today()

    all_payments = (
        db.query(Payment)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )

    if period == "today":
        payments = [
            p for p in all_payments
            if p.payment_date == today
        ]
    elif period == "month":
        payments = [
            p for p in all_payments
            if p.payment_date.year == today.year
            and p.payment_date.month == today.month
        ]
    else:
        period = "all"
        payments = all_payments

    total_revenue = sum(p.amount for p in all_payments)
    today_revenue = sum(
        p.amount for p in all_payments
        if p.payment_date == today
    )
    month_revenue = sum(
        p.amount for p in all_payments
        if p.payment_date.year == today.year
        and p.payment_date.month == today.month
    )

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
            "payment_groups": payment_groups,
            "total_revenue": total_revenue,
            "today_revenue": today_revenue,
            "month_revenue": month_revenue,
            "period": period,
        },
    )


@app.post("/members/{member_id}/renew")
def renew_membership(
    member_id: int,
    amount: int = Form(...),
    db: Session = Depends(get_db),
):
    member = db.query(Member).filter(Member.id == member_id).first()

    if member is None:
        return {"error": "Member not found"}

    gym = get_or_create_gym(db)

    fee = gym.monthly_fee

    if fee <= 0:
        return {"error": "Monthly renewal fee is not configured"}

    if amount <= 0 or amount % fee != 0:
        return {
            "error": f"Invalid payment amount. Enter a multiple of {fee}."
        }

    months_paid = amount // fee

    today = date.today()

    if member.payment_due_date < today:
        start_date = today
    else:
        start_date = member.payment_due_date

    member.payment_due_date = (
        start_date + relativedelta(months=months_paid)
    )
    member.status = "Active"

    payment = Payment(
        member_id=member.id,
        member_name=member.full_name,
        amount=amount,
        payment_date=today,
        membership_type="Monthly",
        payment_type="Renewal",
    )

    db.add(payment)
    db.commit()

    return RedirectResponse(
        url=f"/members/{member_id}",
        status_code=303,
    )


@app.get("/gym-settings")
def gym_settings(
    request: Request,
    db: Session = Depends(get_db),
):
    gym = get_or_create_gym(db)

    return templates.TemplateResponse(
        request=request,
        name="gym_settings.html",
        context={"gym": gym},
    )


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
        return {"error": "Registration fee cannot be negative"}

    if monthly_fee <= 0:
        return {"error": "Monthly renewal fee must be greater than zero"}

    gym.name = name.strip() or "My Gym"
    gym.currency = currency.strip() or "GHS"
    gym.registration_fee = registration_fee
    gym.monthly_fee = monthly_fee

    db.commit()

    return RedirectResponse(
        url="/gym-settings",
        status_code=303,
    )
