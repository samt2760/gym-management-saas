from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_permission
from app.models import Gym, User
from app.web import get_db, templates

router = APIRouter()


@router.get("/gym-settings")
def gym_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.view")),
):
    gym = db.query(Gym).filter(
        Gym.id == user.gym_id
    ).first()

    return templates.TemplateResponse(
        request=request,
        name="gym_settings.html",
        context={
            "gym": gym,
                "current_user": user,
        },
    )


@router.post("/gym-settings")
def update_gym_settings(
    name: str = Form(...),
    currency: str = Form(...),
    registration_fee: int = Form(...),
    monthly_fee: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.edit")),
):
    gym = db.query(Gym).filter(
        Gym.id == user.gym_id
    ).first()

    if gym is None:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    if registration_fee < 0:
        return {
            "error": "Registration fee cannot be negative"
        }

    if monthly_fee <= 0:
        return {
            "error": "Monthly renewal fee must be greater than zero"
        }

    gym.name = name.strip() or "My Gym"
    gym.currency = currency.strip() or "GHS"
    gym.registration_fee = registration_fee
    gym.monthly_fee = monthly_fee

    db.commit()

    return RedirectResponse(
        url="/gym-settings",
        status_code=303,
    )
