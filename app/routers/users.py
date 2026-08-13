import os
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth
from app.tags import validate_username
from app.image_moderation import check_image
from app.routers.friends import _are_friends
from app.routers.shop import _gifts_received

router = APIRouter(prefix="/users", tags=["users"])

# ВАЖНО: файлы пишем в корневой uploads (backend/uploads), который отдаёт StaticFiles
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "avatars"
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
AVATAR_UPLOAD_LIMIT = 5 * 1024 * 1024  # 5 МБ


def _check_image_signature(data: bytes, content_type: str) -> bool:
    """Проверяем реальные байты файла, а не только заявленный content_type."""
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if content_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    return False


def _decor_info(db: Session, user: models.User):
    if not user.active_decoration:
        return None, None
    item = (
        db.query(models.ShopItem)
        .filter(models.ShopItem.id == user.active_decoration)
        .first()
    )
    return (item.name if item else None), (item.emoji if item else None)


def _me_out(db: Session, user: models.User) -> dict:
    data = schemas.UserOut.model_validate(user).model_dump()
    name, emoji = _decor_info(db, user)
    data["active_decoration_name"] = name
    data["active_decoration_emoji"] = emoji
    return data


def _public_out(db: Session, user: models.User) -> dict:
    data = schemas.UserPublicOut.model_validate(user).model_dump()
    name, emoji = _decor_info(db, user)
    data["active_decoration_name"] = name
    data["active_decoration_emoji"] = emoji
    data["gifts"] = []
    return data


@router.get("/me", response_model=schemas.UserOut)
def get_me(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return _me_out(db, current_user)


@router.get("/search", response_model=List[schemas.UserPublicOut])
def search_users(
    q: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if not q.strip():
        return []
    term = q.strip().lstrip("@")
    query = f"%{term}%"
    rows = (
        db.query(models.User)
        .filter(
            models.User.status == models.UserStatus.active,
            (models.User.name.ilike(query))
            | (models.User.username.ilike(query))
            | (models.User.email.ilike(query)),
        )
        .limit(20)
        .all()
    )
    return [_public_out(db, u) for u in rows]


@router.get("/{user_id}", response_model=schemas.UserPublicOut)
def get_user_profile(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    data = _public_out(db, user)

    visibility = user.gifts_visibility or "all"
    if user_id == current_user.id:
        visible = True
    elif visibility == "all":
        visible = True
    elif visibility == "friends":
        visible = _are_friends(db, user_id, current_user.id)
    else:  # nobody
        visible = False

    if visible:
        data["gifts"] = [g.model_dump() for g in _gifts_received(db, user_id)]
    return data


@router.post("/me/avatar", response_model=schemas.UserOut)
def upload_avatar(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    ext = ALLOWED_TYPES.get(file.content_type)
    if not ext:
        raise HTTPException(status_code=400, detail="Недопустимый формат файла (нужен jpg/png/webp)")

    data = file.file.read()
    if len(data) > AVATAR_UPLOAD_LIMIT:
        raise HTTPException(status_code=400, detail="Фото слишком большое (максимум 5 МБ)")
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if not _check_image_signature(data, file.content_type):
        raise HTTPException(status_code=400, detail="Файл не является изображением")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if current_user.avatar_url:
        old_path = (Path(__file__).resolve().parents[2] / current_user.avatar_url.lstrip("/")).resolve()
        try:
            if old_path.is_relative_to(UPLOAD_DIR.resolve()):
                old_path.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as fh:
        fh.write(data)

    # ИИ-фильтрация: порнография/нагота/свастика отклоняется сразу
    try:
        flagged, reasons = check_image(dest)
        if flagged:
            dest.unlink(missing_ok=True)
            detail = "; ".join(reasons) or "изображение не прошло проверку"
            raise HTTPException(status_code=400, detail=f"Фото отклонено модератором: {detail}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[image_moderation] ошибка проверки аватара {dest}: {e}")

    current_user.avatar_url = f"/uploads/avatars/{filename}"
    db.commit()
    db.refresh(current_user)
    return current_user


@router.patch("/me", response_model=schemas.UserOut)
def update_me(
    bio: str | None = None,
    name: str | None = None,
    username: str | None = None,
    avatar_url: str | None = None,
    e2e_public_key: str | None = None,
    messages_policy: str | None = None,
    gifts_visibility: str | None = None,
    gifts_policy: str | None = None,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if bio is not None:
        current_user.bio = bio
    if name is not None:
        current_user.name = name
    if username is not None:
        new_username = validate_username(username)
        if new_username:
            taken = (
                db.query(models.User)
                .filter(
                    models.User.username == new_username,
                    models.User.id != current_user.id,
                )
                .first()
            )
            if taken:
                raise HTTPException(status_code=400, detail="Этот тег уже занят")
        current_user.username = new_username
    if avatar_url is not None:
        current_user.avatar_url = avatar_url
    if e2e_public_key is not None:
        current_user.e2e_public_key = e2e_public_key
    if messages_policy is not None:
        if messages_policy not in ("all", "friends"):
            raise HTTPException(status_code=400, detail="Недопустимое значение messages_policy")
        current_user.messages_policy = messages_policy
    if gifts_visibility is not None:
        if gifts_visibility not in ("all", "friends", "nobody"):
            raise HTTPException(status_code=400, detail="Недопустимое значение gifts_visibility")
        current_user.gifts_visibility = gifts_visibility
    if gifts_policy is not None:
        if gifts_policy not in ("all", "friends", "none"):
            raise HTTPException(status_code=400, detail="Недопустимое значение gifts_policy")
        current_user.gifts_policy = gifts_policy
    db.commit()
    db.refresh(current_user)
    return current_user
