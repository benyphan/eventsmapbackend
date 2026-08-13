from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app import models, schemas, auth
from app.routers.notifications import send_notification

router = APIRouter(prefix="/friends", tags=["friends"])


def _friend_out(r: models.FriendRequest) -> schemas.FriendRequestOut:
    return schemas.FriendRequestOut(
        id=r.id,
        from_user_id=r.from_user_id,
        to_user_id=r.to_user_id,
        status=r.status.value if hasattr(r.status, "value") else str(r.status),
        created_at=r.created_at,
        from_user_name=r.from_user.name if r.from_user else None,
        to_user_name=r.to_user.name if r.to_user else None,
        from_user_avatar=r.from_user.avatar_url if r.from_user else None,
    )


def _are_friends(db: Session, a_id: str, b_id: str) -> bool:
    return (
        db.query(models.FriendRequest)
        .filter(
            models.FriendRequest.status == models.FriendStatus.accepted,
            or_(
                (models.FriendRequest.from_user_id == a_id) & (models.FriendRequest.to_user_id == b_id),
                (models.FriendRequest.from_user_id == b_id) & (models.FriendRequest.to_user_id == a_id),
            ),
        )
        .first()
        is not None
    )


@router.get("/", response_model=List[schemas.FriendRequestOut])
def my_friends(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    rows = (
        db.query(models.FriendRequest)
        .filter(
            models.FriendRequest.status == models.FriendStatus.accepted,
            or_(
                models.FriendRequest.from_user_id == current_user.id,
                models.FriendRequest.to_user_id == current_user.id,
            ),
        )
        .order_by(models.FriendRequest.created_at.desc())
        .all()
    )
    return [_friend_out(r) for r in rows]


@router.get("/requests", response_model=List[schemas.FriendRequestOut])
def incoming_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    rows = (
        db.query(models.FriendRequest)
        .filter(
            models.FriendRequest.to_user_id == current_user.id,
            models.FriendRequest.status == models.FriendStatus.pending,
        )
        .order_by(models.FriendRequest.created_at.desc())
        .all()
    )
    return [_friend_out(r) for r in rows]


@router.post("/{user_id}", response_model=schemas.FriendRequestOut)
def send_friend_request(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя в друзья")
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    existing = (
        db.query(models.FriendRequest)
        .filter(
            or_(
                (models.FriendRequest.from_user_id == current_user.id)
                & (models.FriendRequest.to_user_id == user_id),
                (models.FriendRequest.from_user_id == user_id)
                & (models.FriendRequest.to_user_id == current_user.id),
            ),
            models.FriendRequest.status.in_(
                [models.FriendStatus.pending, models.FriendStatus.accepted]
            ),
        )
        .first()
    )
    if existing:
        if existing.status == models.FriendStatus.accepted:
            raise HTTPException(status_code=400, detail="Вы уже друзья")
        raise HTTPException(status_code=400, detail="Заявка уже отправлена")

    req = models.FriendRequest(from_user_id=current_user.id, to_user_id=user_id)
    db.add(req)
    db.commit()
    db.refresh(req)
    send_notification(
        db, user_id,
        "Запрос в друзья",
        f"{current_user.name} хочет добавить вас в друзья.",
    )
    db.commit()
    return _friend_out(req)


@router.patch("/{request_id}")
def decide_friend_request(
    request_id: str,
    status: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    req = db.query(models.FriendRequest).filter(models.FriendRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if req.to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Это не ваша заявка")
    if status not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="Неверный статус")
    req.status = models.FriendStatus.accepted if status == "accepted" else models.FriendStatus.rejected
    db.commit()
    db.refresh(req)
    if status == "accepted":
        send_notification(
            db, req.from_user_id,
            "Заявка принята",
            f"{current_user.name} принял(а) вашу заявку в друзья.",
        )
        db.commit()
    return _friend_out(req)
