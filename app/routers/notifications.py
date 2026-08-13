from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth

router = APIRouter(prefix="/notifications", tags=["notifications"])


def send_notification(db: Session, user_id: str, title: str, body: Optional[str] = None) -> models.Notification:
    """Создаёт уведомление для пользователя (без commit — коммитит вызывающий)."""
    n = models.Notification(user_id=user_id, title=title, body=body)
    db.add(n)
    db.flush()
    return n


@router.get("/", response_model=List[schemas.NotificationOut])
def list_notifications(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Notification)
        .filter(models.Notification.user_id == current_user.id)
        .order_by(models.Notification.created_at.desc())
        .all()
    )


@router.patch("/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_read(
    notification_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    n = (
        db.query(models.Notification)
        .filter(
            models.Notification.id == notification_id,
            models.Notification.user_id == current_user.id,
        )
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n
