from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth
from app.routers.notifications import send_notification

router = APIRouter(prefix="/admin", tags=["admin"])


class RoleUpdate(BaseModel):
    role: str  # user | moderator | admin


@router.get("/stats")
def admin_stats(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    users_total = db.query(func.count(models.User.id)).scalar()
    events_total = db.query(func.count(models.Event.id)).scalar()
    events_by_status = dict(
        db.query(models.Event.status, func.count(models.Event.id))
        .group_by(models.Event.status)
        .all()
    )
    reports_open = db.query(func.count(models.Report.id)).filter(
        models.Report.status == models.ReportStatus.open
    ).scalar()
    return {
        "users_total": users_total,
        "events_total": events_total,
        "events_by_status": events_by_status,
        "reports_open": reports_open,
    }


@router.get("/events", response_model=List[schemas.EventOut])
def list_all_events(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    query = db.query(models.Event)
    if status:
        query = query.filter(models.Event.status == status)
    return query.order_by(models.Event.created_at.desc()).all()


@router.patch("/events/{event_id}", response_model=schemas.EventOut)
def edit_event(
    event_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    """Позволяет админу отредактировать любые поля мероприятия."""
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    for key, value in payload.items():
        if hasattr(event, key):
            setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/events/{event_id}/moderate", response_model=schemas.EventOut)
def moderate_event(
    event_id: str,
    decision: schemas.ModerationDecision,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    event.status = decision.status
    if decision.status == "published":
        event.moderation_note = None
    db.commit()
    db.refresh(event)

    # Уведомляем организатора о результате модерации
    if decision.status == "published":
        send_notification(
            db, event.owner_id,
            "Мероприятие опубликовано",
            f"«{event.title}» прошло модерацию и теперь видно всем.",
        )
    elif decision.status == "rejected":
        send_notification(
            db, event.owner_id,
            "Мероприятие отклонено",
            f"«{event.title}» не прошло модерацию. Попробуй исправить и создать заново.",
        )
    db.commit()
    return event


@router.delete("/events/{event_id}")
def delete_event(
    event_id: str,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    chat_ids = [c[0] for c in db.query(models.Chat.id).filter(models.Chat.event_id == event_id).all()]
    if chat_ids:
        db.query(models.Message).filter(models.Message.chat_id.in_(chat_ids)).delete(synchronize_session=False)
        db.query(models.ChatMember).filter(models.ChatMember.chat_id.in_(chat_ids)).delete(synchronize_session=False)
        db.query(models.Chat).filter(models.Chat.id.in_(chat_ids)).delete(synchronize_session=False)
    db.query(models.EventCriteria).filter(models.EventCriteria.event_id == event_id).delete(synchronize_session=False)
    db.query(models.EventParticipant).filter(models.EventParticipant.event_id == event_id).delete(synchronize_session=False)
    db.delete(event)
    db.commit()
    return {"ok": True}


@router.get("/users", response_model=List[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.patch("/users/{user_id}/ban", response_model=schemas.UserOut)
def ban_user(
    user_id: str,
    payload: schemas.UserBan,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.status = payload.status
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/role", response_model=schemas.UserOut)
def change_role(
    user_id: str,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if payload.role not in ("user", "moderator", "admin"):
        raise HTTPException(status_code=400, detail="Недопустимая роль")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.require_admin),
):
    """Полное удаление аккаунта вместе со всеми связанными записями."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить свой собственный аккаунт")

    own_events = [e[0] for e in db.query(models.Event.id).filter(models.Event.owner_id == user_id).all()]
    if own_events:
        chat_ids = [c[0] for c in db.query(models.Chat.id).filter(models.Chat.event_id.in_(own_events)).all()]
        if chat_ids:
            db.query(models.Message).filter(models.Message.chat_id.in_(chat_ids)).delete(synchronize_session=False)
            db.query(models.ChatMember).filter(models.ChatMember.chat_id.in_(chat_ids)).delete(synchronize_session=False)
            db.query(models.Chat).filter(models.Chat.id.in_(chat_ids)).delete(synchronize_session=False)
        db.query(models.EventCriteria).filter(models.EventCriteria.event_id.in_(own_events)).delete(synchronize_session=False)
        db.query(models.EventParticipant).filter(models.EventParticipant.event_id.in_(own_events)).delete(synchronize_session=False)
        db.query(models.Event).filter(models.Event.id.in_(own_events)).delete(synchronize_session=False)

    db.query(models.Message).filter(models.Message.sender_id == user_id).delete(synchronize_session=False)
    db.query(models.ChatMember).filter(models.ChatMember.user_id == user_id).delete(synchronize_session=False)
    db.query(models.EventParticipant).filter(models.EventParticipant.user_id == user_id).delete(synchronize_session=False)
    db.query(models.Notification).filter(models.Notification.user_id == user_id).delete(synchronize_session=False)
    db.query(models.Purchase).filter(models.Purchase.user_id == user_id).delete(synchronize_session=False)
    db.query(models.Gift).filter(
        (models.Gift.from_user_id == user_id) | (models.Gift.to_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.Post).filter(models.Post.user_id == user_id).delete(synchronize_session=False)
    db.query(models.FriendRequest).filter(
        (models.FriendRequest.from_user_id == user_id) | (models.FriendRequest.to_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.Report).filter(models.Report.reporter_id == user_id).delete(synchronize_session=False)
    db.query(models.User).filter(models.User.referred_by_id == user_id).update(
        {models.User.referred_by_id: None}, synchronize_session=False
    )

    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/posts", response_model=List[schemas.PostOut])
def list_posts_for_moderation(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    query = db.query(models.Post)
    if status:
        query = query.filter(models.Post.moderation_status == status)
    posts = query.order_by(models.Post.created_at.desc()).all()
    return [_post_out(p) for p in posts]


@router.patch("/posts/{post_id}/moderate", response_model=schemas.PostOut)
def moderate_post(
    post_id: str,
    decision: schemas.PostDecision,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    from pathlib import Path

    post = db.query(models.Post).filter(models.Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if decision.status not in ("published", "rejected"):
        raise HTTPException(status_code=400, detail="Неверный статус")
    post.moderation_status = decision.status
    if decision.status == "rejected":
        for url in (list(post.image_urls or []) + ([post.image_url] if post.image_url else [])):
            try:
                old_path = (Path(__file__).resolve().parents[2] / url.lstrip("/")).resolve()
                if old_path.is_relative_to(
                    (Path(__file__).resolve().parents[2] / "uploads" / "posts").resolve()
                ):
                    old_path.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
    db.commit()
    db.refresh(post)

    send_notification(
        db, post.user_id,
        "Модерация поста",
        ("Пост опубликован." if decision.status == "published"
         else "Пост отклонён модератором."),
    )
    db.commit()
    return _post_out(post)


def _post_out(p: models.Post) -> schemas.PostOut:
    return schemas.PostOut(
        id=p.id,
        user_id=p.user_id,
        text=p.text,
        image_url=p.image_url,
        image_urls=p.image_urls or None,
        moderation_status=p.moderation_status,
        moderation_note=p.moderation_note,
        created_at=p.created_at,
        user_name=p.user.name if p.user else None,
    )
