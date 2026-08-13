import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth
from app.moderation import contains_banned
from app.image_moderation import check_image

router = APIRouter(prefix="/posts", tags=["posts"])

# ВАЖНО: файлы пишем в корневой uploads (backend/uploads), который отдаёт StaticFiles
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "posts"
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}

POST_UPLOAD_LIMIT = 5 * 1024 * 1024  # 5 МБ
MAX_POST_IMAGES = 8
POST_INTERVAL_SECONDS = 600  # антиспам: посты не чаще раза в 10 минут


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


def _check_spam(db: Session, user: models.User):
    last = (
        db.query(models.Post)
        .filter(models.Post.user_id == user.id)
        .order_by(models.Post.created_at.desc())
        .first()
    )
    if last and last.created_at:
        elapsed = (datetime.utcnow() - last.created_at).total_seconds()
        if elapsed < POST_INTERVAL_SECONDS:
            wait = int(POST_INTERVAL_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Посты можно публиковать не чаще раза в 10 минут. Подождите {wait} с.",
            )


@router.get("/user/{user_id}", response_model=List[schemas.PostOut])
def list_user_posts(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    query = db.query(models.Post).filter(models.Post.user_id == user_id)
    if user_id != current_user.id:
        # Чужой профиль — показываем только прошедшие модерацию посты
        query = query.filter(models.Post.moderation_status == "published")
    posts = query.order_by(models.Post.created_at.desc()).all()
    return [_post_out(p) for p in posts]


def _create_post_with_moderation(
    db: Session, user: models.User, text: str, image_urls=None, image_reasons=None
) -> models.Post:
    # Автомодерация: запрещённый текст или выявленный ИИ-контент на картинках
    # отправляют пост на модерацию. Чистые посты публикуются сразу.
    reasons = []
    if contains_banned(text):
        reasons.append("подозрительный текст")
    if image_reasons:
        reasons.extend(image_reasons)

    status = "pending" if reasons else "published"
    post = models.Post(
        user_id=user.id,
        text=text,
        image_url=image_urls[0] if image_urls else None,
        image_urls=image_urls or None,
        moderation_status=status,
        moderation_note="; ".join(reasons) if reasons else None,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.post("/", response_model=schemas.PostOut)
def create_post(
    payload: schemas.PostCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _check_spam(db, current_user)
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пост не может быть пустым")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Пост слишком длинный (максимум 2000 символов)")
    post = _create_post_with_moderation(db, current_user, text)
    return _post_out(post)


@router.post("/with_image", response_model=schemas.PostOut)
def create_post_with_image(
    text: str = Form(""),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _check_spam(db, current_user)
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пост не может быть пустым")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Пост слишком длинный (максимум 2000 символов)")
    if len(files) > MAX_POST_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Можно прикрепить не больше {MAX_POST_IMAGES} фотографий",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    urls = []
    files_on_disk = []
    for file in files:
        ext = ALLOWED_TYPES.get(file.content_type)
        if not ext:
            raise HTTPException(status_code=400, detail="Недопустимый формат файла (нужен jpg/png/webp/gif)")
        data = file.file.read()
        if len(data) > POST_UPLOAD_LIMIT:
            raise HTTPException(status_code=400, detail="Картинка слишком большая (максимум 5 МБ)")

        filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"
        dest = UPLOAD_DIR / filename
        with dest.open("wb") as fh:
            fh.write(data)
        urls.append(f"/uploads/posts/{filename}")
        files_on_disk.append(dest)

    # ИИ-фильтрация: порнография/нагота и свастика уходят на модерацию
    image_reasons = []
    for dest in files_on_disk:
        try:
            flagged, reasons = check_image(dest)
            if flagged:
                image_reasons.extend(reasons)
        except Exception as e:
            print(f"[image_moderation] ошибка проверки {dest}: {e}")

    post = _create_post_with_moderation(
        db, current_user, text, image_urls=urls, image_reasons=image_reasons
    )
    return _post_out(post)


@router.delete("/{post_id}")
def delete_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    post = db.query(models.Post).filter(models.Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нельзя удалить чужой пост")
    _remove_post_images(post)
    db.delete(post)
    db.commit()
    return {"ok": True}


def _remove_post_images(post: models.Post):
    if not post.image_urls and not post.image_url:
        return
    for url in (list(post.image_urls or []) + ([post.image_url] if post.image_url else [])):
        try:
            old_path = (Path(__file__).resolve().parents[2] / url.lstrip("/")).resolve()
            if old_path.is_relative_to(UPLOAD_DIR.resolve()):
                old_path.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass
