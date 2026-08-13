import base64
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db
from app import models, schemas, auth
from app.routers.friends import _are_friends

router = APIRouter(prefix="/chats", tags=["chats"])


def _can_write_to(db: Session, me_id: str, other_id: str) -> bool:
    other = db.query(models.User).filter(models.User.id == other_id).first()
    if not other:
        return False
    if other.messages_policy != "friends":
        return True
    return _are_friends(db, me_id, other_id)


def _chat_out(db: Session, chat: models.Chat, me_id: str) -> schemas.ChatOut:
    members = (
        db.query(models.ChatMember)
        .filter(models.ChatMember.chat_id == chat.id)
        .all()
    )
    other = None
    title = None
    event_id = chat.event_id
    if chat.is_group:
        if chat.event_id:
            ev = db.query(models.Event).filter(models.Event.id == chat.event_id).first()
            if ev:
                title = ev.title
    else:
        for m in members:
            if m.user_id != me_id:
                u = db.query(models.User).filter(models.User.id == m.user_id).first()
                if u:
                    other = u
                    title = u.name
                break
    last = (
        db.query(models.Message)
        .filter(models.Message.chat_id == chat.id)
        .order_by(models.Message.created_at.desc())
        .first()
    )
    last_out = _message_out(db, last) if last else None
    return schemas.ChatOut(
        id=chat.id,
        is_group=chat.is_group,
        title=title,
        event_id=event_id,
        member_count=len(members),
        other_user=other,
        last_message=last_out,
    )


def _message_out(db: Session, m: models.Message) -> schemas.MessageOut:
    sender = db.query(models.User).filter(models.User.id == m.sender_id).first()
    return schemas.MessageOut(
        id=m.id,
        chat_id=m.chat_id,
        sender_id=m.sender_id,
        sender_name=sender.name if sender else None,
        content_enc=base64.b64encode(bytes(m.content_enc)).decode() if m.content_enc else None,
        created_at=m.created_at,
    )


@router.get("/", response_model=List[schemas.ChatOut])
def list_chats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    chat_ids = [
        r[0] for r in db.query(models.ChatMember.chat_id)
        .filter(models.ChatMember.user_id == current_user.id)
        .all()
    ]
    chats = (
        db.query(models.Chat)
        .filter(models.Chat.id.in_(chat_ids))
        .order_by(models.Chat.created_at.desc()) if chat_ids else []
    )
    return [_chat_out(db, c, current_user.id) for c in chats]


@router.post("/", response_model=schemas.ChatOut)
def create_or_get_chat(
    payload: schemas.ChatCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if payload.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя создать чат с собой")
    target = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if not _can_write_to(db, current_user.id, target.id):
        raise HTTPException(
            status_code=403,
            detail=f"{target.name} разрешил(а) писать только друзьям",
        )

    # Ищем существующий личный чат между двумя пользователями
    my_chats = [r[0] for r in db.query(models.ChatMember.chat_id)
                .filter(models.ChatMember.user_id == current_user.id).all()]
    if my_chats:
        rows = (
            db.query(models.Chat)
            .join(models.ChatMember, models.ChatMember.chat_id == models.Chat.id)
            .filter(
                models.Chat.id.in_(my_chats),
                models.Chat.is_group == False,
                models.ChatMember.user_id == payload.user_id,
            )
            .all()
        )
        if rows:
            return _chat_out(db, rows[0], current_user.id)

    chat = models.Chat(is_group=False)
    db.add(chat)
    db.flush()
    db.add(models.ChatMember(chat_id=chat.id, user_id=current_user.id))
    db.add(models.ChatMember(chat_id=chat.id, user_id=payload.user_id))
    db.commit()
    db.refresh(chat)
    return _chat_out(db, chat, current_user.id)


def _sync_event_chat_members(db: Session, chat: models.Chat, event_id: str):
    """Добавляет в групповой чат мероприятия владельца и всех одобренных участников."""
    user_ids = {chat_member.user_id for chat_member in
                db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat.id).all()}
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        return
    target_ids = {event.owner_id}
    for p in db.query(models.EventParticipant).filter(
        models.EventParticipant.event_id == event_id,
        models.EventParticipant.status == models.ParticipantStatus.approved,
    ).all():
        target_ids.add(p.user_id)
    for uid in target_ids - user_ids:
        db.add(models.ChatMember(chat_id=chat.id, user_id=uid))


@router.get("/event/{event_id}", response_model=schemas.ChatOut)
def get_or_create_event_chat(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Возвращает (или создаёт) общий чат мероприятия для участников."""
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    if event.owner_id != current_user.id:
        member = db.query(models.EventParticipant).filter(
            models.EventParticipant.event_id == event_id,
            models.EventParticipant.user_id == current_user.id,
            models.EventParticipant.status == models.ParticipantStatus.approved,
        ).first()
        if not member:
            raise HTTPException(
                status_code=403,
                detail="Чат мероприятия доступен организатору и одобренным участникам",
            )

    chat = (
        db.query(models.Chat)
        .filter(models.Chat.event_id == event_id, models.Chat.is_group == True)
        .first()
    )
    if not chat:
        chat = models.Chat(event_id=event_id, is_group=True)
        db.add(chat)
        db.flush()
        db.add(models.ChatMember(chat_id=chat.id, user_id=event.owner_id))
        db.commit()
        db.refresh(chat)
    else:
        _sync_event_chat_members(db, chat, event_id)
        db.commit()

    # Гарантируем, что текущий пользователь — участник чата
    me = (
        db.query(models.ChatMember)
        .filter(models.ChatMember.chat_id == chat.id, models.ChatMember.user_id == current_user.id)
        .first()
    )
    if not me:
        db.add(models.ChatMember(chat_id=chat.id, user_id=current_user.id))
        db.commit()
    return _chat_out(db, chat, current_user.id)


@router.get("/{chat_id}/messages", response_model=List[schemas.MessageOut])
def list_messages(
    chat_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Вы не участник чата")
    msgs = (
        db.query(models.Message)
        .filter(models.Message.chat_id == chat_id, models.Message.is_deleted == False)
        .order_by(models.Message.created_at.asc())
        .all()
    )
    return [_message_out(db, m) for m in msgs]


@router.post("/{chat_id}/messages", response_model=schemas.MessageOut)
def send_message(
    chat_id: str,
    payload: schemas.MessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    member = (
        db.query(models.ChatMember)
        .filter(
            models.ChatMember.chat_id == chat_id,
            models.ChatMember.user_id == current_user.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=403, detail="Вы не участник чата")

    chat = db.query(models.Chat).filter(models.Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")

    other_id = None
    if not chat.is_group:
        other = (
            db.query(models.ChatMember)
            .filter(
                models.ChatMember.chat_id == chat_id,
                models.ChatMember.user_id != current_user.id,
            )
            .first()
        )
        if other:
            other_id = other.user_id
    if other_id and not _can_write_to(db, current_user.id, other_id):
        other_user = db.query(models.User).filter(models.User.id == other_id).first()
        raise HTTPException(
            status_code=403,
            detail=f"{other_user.name if other_user else 'Пользователь'} разрешил(а) писать только друзьям",
        )

    try:
        raw = base64.b64decode(payload.content_enc)
    except Exception:
        raise HTTPException(status_code=400, detail="Некорректное шифрованное содержимое")
    if not raw:
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    msg = models.Message(chat_id=chat_id, sender_id=current_user.id, content_enc=raw)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _message_out(db, msg)
