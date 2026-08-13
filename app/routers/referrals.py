from pydantic import BaseModel

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, auth

router = APIRouter(prefix="/referrals", tags=["referrals"])


class ReferredUserOut(BaseModel):
    id: str
    name: str
    created_at: str | None = None


class ReferralOut(BaseModel):
    code: str
    referral_count: int
    credits: int
    invited: list[ReferredUserOut]


@router.get("/me", response_model=ReferralOut)
def get_my_referral(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    invited = (
        db.query(models.User)
        .filter(models.User.referred_by_id == current_user.id)
        .order_by(models.User.created_at.desc())
        .all()
    )
    return ReferralOut(
        code=current_user.referral_code,
        referral_count=current_user.referral_count or 0,
        credits=current_user.credits or 0,
        invited=[
            ReferredUserOut(
                id=u.id,
                name=u.name,
                created_at=u.created_at.isoformat() if u.created_at else None,
            )
            for u in invited
        ],
    )
