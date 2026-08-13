from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, String
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID, ST_Distance
from geoalchemy2.shape import to_shape

from app.database import get_db
from app import models, schemas, auth
from app.routers.notifications import send_notification

router = APIRouter(prefix="/events", tags=["events"])

MAX_PARTICIPANTS_LIMIT = 20
MAX_EVENTS_PER_HOUR = 10
# Подозрительные слова: если встреча намекает на деньги/риски — на модерацию
SUSPICIOUS_WORDS = [
    "деньги", "заработок", "крипто", "казино", "инвестиц", "быстрый доход",
    "оформить", "работа на дому", "перевод", "оплата", "продам", "куплю",
    "наркотик", "оружие", "несовершеннолетн", "бесплатн", "розыгрыш",
]


def looks_suspicious(title: str, description: str, max_participants: Optional[int]) -> Optional[str]:
    """Возвращает причину, почему встреча уходит на модерацию, или None."""
    if max_participants and max_participants >= 50:
        return "Слишком большое количество участников"
    text = f"{title or ''} {description or ''}".lower()
    for word in SUSPICIOUS_WORDS:
        if word in text:
            return f"Подозрительные формулировки («{word}»)"
    if len((description or "").strip()) < 10 and not max_participants:
        return "Очень короткое описание"
    return None


def _participant_out(p: models.EventParticipant, me_id: Optional[str] = None) -> schemas.ParticipantOut:
    return schemas.ParticipantOut(
        id=p.id,
        event_id=p.event_id,
        user_id=p.user_id,
        user_name=p.user.name if p.user else None,
        avatar_url=p.user.avatar_url if p.user else None,
        status=p.status.value if hasattr(p.status, "value") else str(p.status),
        is_me=(me_id is not None and p.user_id == me_id),
        requested_at=p.requested_at,
        decided_at=p.decided_at,
    )


def _with_current_user(event: models.Event, user_id: Optional[str]) -> models.Event:
    """Подмешивает флаги текущего пользователя для ответа клиенту."""
    event.is_owner = user_id is not None and event.owner_id == user_id
    event.archived = (event.end_at or event.start_at) <= datetime.utcnow()
    event.my_participant_status = None
    if user_id:
        for p in event.participants:
            if p.user_id == user_id:
                event.my_participant_status = p.status.value if hasattr(p.status, "value") else str(p.status)
                break
    return event


@router.get("/", response_model=List[schemas.EventOut])
def list_events_nearby(
    lat: float,
    lng: float,
    radius_m: int = 5000,
    category: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Возвращает опубликованные мероприятия в радиусе radius_m метров от точки."""
    point = ST_SetSRID(ST_MakePoint(lng, lat), 4326)
    now = datetime.utcnow()
    query = db.query(models.Event, ST_Distance(models.Event.location, point).label("distance_m")).filter(
        models.Event.status == models.EventStatus.published,
        func.coalesce(models.Event.end_at, models.Event.start_at) > now,
        ST_DWithin(models.Event.location, point, radius_m),
    )
    if category:
        query = query.filter(models.Event.category == category)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            models.Event.title.ilike(like)
            | models.Event.description.ilike(like)
            | models.Event.tags.cast(String).ilike(like)
        )
    rows = query.order_by("distance_m").all()
    events = []
    for ev, dist in rows:
        ev.distance_m = int(dist) if dist is not None else None
        events.append(ev)
    return events


@router.post("/", response_model=schemas.EventOut)
def create_event(
    event_in: schemas.EventCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if event_in.max_participants and event_in.max_participants > MAX_PARTICIPANTS_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Слишком много участников: максимум {MAX_PARTICIPANTS_LIMIT}",
        )

    # Нельзя создавать мероприятие в прошлом
    start_at_utc = event_in.start_at
    if start_at_utc.tzinfo is not None:
        start_at_utc = start_at_utc.astimezone(timezone.utc).replace(tzinfo=None)
    if start_at_utc <= datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="Нельзя создавать мероприятие в прошлом. Выбери будущее время",
        )

    hour_ago = datetime.utcnow() - timedelta(hours=1)
    created_count = (
        db.query(func.count(models.Event.id))
        .filter(
            models.Event.owner_id == current_user.id,
            models.Event.created_at >= hour_ago,
        )
        .scalar()
    )
    if created_count >= MAX_EVENTS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много мероприятий за час: максимум {MAX_EVENTS_PER_HOUR}",
        )

    point = f"POINT({event_in.lng} {event_in.lat})"

    # Автомодерация: обычные встречи публикуются сразу, подозрительные уходят на модерацию
    reason = looks_suspicious(event_in.title, event_in.description or "", event_in.max_participants)
    if reason:
        status = models.EventStatus.pending_moderation
        note = reason
    else:
        status = models.EventStatus.published
        note = None

    event = models.Event(
        owner_id=current_user.id,
        title=event_in.title,
        description=event_in.description,
        category=event_in.category,
        location=point,
        address=event_in.address,
        start_at=event_in.start_at,
        end_at=event_in.end_at,
        visibility=event_in.visibility,
        max_participants=event_in.max_participants,
        status=status,
        moderation_note=note,
        tags=[t.strip().lower() for t in (event_in.tags or []) if t and t.strip()],
    )
    db.add(event)
    db.flush()  # получить event.id до коммита

    if event_in.criteria:
        criteria = models.EventCriteria(event_id=event.id, **event_in.criteria.model_dump())
        db.add(criteria)

    if status == models.EventStatus.published:
        send_notification(
            db, current_user.id,
            "Мероприятие опубликовано",
            f"«{event.title}» прошло автоматическую проверку и уже на карте.",
        )
    else:
        send_notification(
            db, current_user.id,
            "Мероприятие на модерации",
            f"«{event.title}» отправлено на модерацию ({note}). Обычно это занимает до 24 часов.",
        )

    db.commit()
    db.refresh(event)
    return _with_current_user(event, current_user.id)


@router.get("/mine", response_model=List[schemas.EventOut])
def my_events(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Мероприятия текущего пользователя: созданные им и те, куда он подавал заявку."""
    events = (
        db.query(models.Event)
        .outerjoin(
            models.EventParticipant,
            (models.EventParticipant.event_id == models.Event.id)
            & (models.EventParticipant.user_id == current_user.id),
        )
        .filter(
            (models.Event.owner_id == current_user.id)
            | (models.EventParticipant.user_id == current_user.id),
        )
        .order_by(models.Event.start_at.desc())
        .all()
    )
    return [_with_current_user(ev, current_user.id) for ev in events]


@router.get("/{event_id}", response_model=schemas.EventOut)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    return _with_current_user(event, current_user.id)


@router.get("/{event_id}/participants", response_model=List[schemas.ParticipantOut])
def list_participants(
    event_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Список заявок. Организатор видит все, остальные — только одобренных."""
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    rows = (
        db.query(models.EventParticipant)
        .filter(models.EventParticipant.event_id == event_id)
        .order_by(models.EventParticipant.requested_at)
        .all()
    )
    if event.owner_id != current_user.id:
        rows = [p for p in rows if p.status == models.ParticipantStatus.approved]
    return [_participant_out(p, current_user.id) for p in rows]


@router.post("/{event_id}/join")
def join_event(
    event_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event or event.status != models.EventStatus.published:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    if (event.end_at or event.start_at) <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Мероприятие уже завершилось")
    if event.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Вы организатор этого мероприятия")

    # Проверка критериев на бэкенде (нельзя обойти с клиента)
    if event.criteria:
        c = event.criteria
        if current_user.birth_date and c.min_age:
            age = (datetime.utcnow() - current_user.birth_date).days // 365
            if age < c.min_age or (c.max_age and age > c.max_age):
                raise HTTPException(status_code=403, detail="Вы не подходите по возрастному критерию")
        if c.gender and c.gender != "any" and current_user.gender and c.gender != current_user.gender:
            raise HTTPException(status_code=403, detail="Не подходит по критерию пола")

    # Лимит участников: считаем только одобренных
    if event.max_participants:
        approved = (
            db.query(func.count(models.EventParticipant.id))
            .filter(
                models.EventParticipant.event_id == event_id,
                models.EventParticipant.status == models.ParticipantStatus.approved,
            )
            .scalar()
        )
        if approved >= event.max_participants:
            raise HTTPException(status_code=400, detail="Мест больше нет")

    existing = db.query(models.EventParticipant).filter(
        models.EventParticipant.event_id == event_id,
        models.EventParticipant.user_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Заявка уже отправлена")

    participant = models.EventParticipant(
        event_id=event_id,
        user_id=current_user.id,
        status=models.ParticipantStatus.requested,
    )
    db.add(participant)

    # Уведомляем организатора о новой заявке
    send_notification(
        db, event.owner_id,
        "Новая заявка на мероприятие",
        f"{current_user.name} хочет прийти на «{event.title}».",
    )
    db.commit()
    return {"status": models.ParticipantStatus.requested.value}


@router.patch("/{event_id}/participants/{user_id}")
def decide_participant(
    event_id: str,
    user_id: str,
    decision: schemas.ParticipantDecision,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")
    if event.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только организатор может решать по заявкам")

    participant = db.query(models.EventParticipant).filter(
        models.EventParticipant.event_id == event_id,
        models.EventParticipant.user_id == user_id,
    ).first()
    if not participant:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    if decision.status == "approved":
        if event.max_participants:
            approved = (
                db.query(func.count(models.EventParticipant.id))
                .filter(
                    models.EventParticipant.event_id == event_id,
                    models.EventParticipant.status == models.ParticipantStatus.approved,
                )
                .scalar()
            )
            if approved >= event.max_participants:
                raise HTTPException(status_code=400, detail="Мест больше нет")

    participant.status = decision.status
    participant.decided_at = datetime.utcnow()
    db.add(participant)

    if decision.status == "approved":
        send_notification(
            db, user_id,
            "Заявка одобрена",
            f"Организатор подтвердил твоё участие в «{event.title}». Ждём тебя!",
        )
    else:
        send_notification(
            db, user_id,
            "Заявка отклонена",
            f"Организатор отклонил заявку на «{event.title}».",
        )
    db.commit()
    return {"status": participant.status.value}
