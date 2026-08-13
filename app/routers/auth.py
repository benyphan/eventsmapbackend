from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth, mailer
from app.ratelimit import RateLimiter
from app.tags import validate_username

router = APIRouter(prefix="/auth", tags=["auth"])

REFERRAL_BONUS = 100  # баллов за приглашённого друга
REFERRAL_INVITE_BONUS = 50  # баллов пригласившему

CODE_TTL_MINUTES = 10
DEV_CODE_FIELD = "dev_code"

# Антибрутфорс: лимиты по IP
_login_limiter = RateLimiter(max_count=10, window_seconds=60)          # 10 попыток логина/мин
_register_limiter = RateLimiter(max_count=3, window_seconds=60)        # 3 регистрации/мин
_code_limiter = RateLimiter(max_count=5, window_seconds=60)            # 5 кодов/мин
_reset_limiter = RateLimiter(max_count=5, window_seconds=300)          # 5 сбросов пароля/5 мин


def _client_ip(request: Request) -> str:
    # Прокси за nginx: берём реальный IP, если nginx передал X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_limit(limiter: RateLimiter, key: str):
    ok, wait = limiter.allow(key)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Слишком много запросов. Подождите {wait} с.")


def _issue_code(db: Session, email: str, purpose: str) -> str:
    code = mailer.generate_code()
    db.query(models.VerifyCode).filter(
        models.VerifyCode.email == email,
        models.VerifyCode.purpose == purpose,
        models.VerifyCode.used.is_(False),
    ).update({"used": True})
    db.add(models.VerifyCode(
        email=email,
        code=code,
        purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(minutes=CODE_TTL_MINUTES),
    ))
    db.commit()
    return code


def _code_is_valid(db: Session, email: str, purpose: str, code: str) -> bool:
    row = (
        db.query(models.VerifyCode)
        .filter(
            models.VerifyCode.email == email,
            models.VerifyCode.purpose == purpose,
            models.VerifyCode.code == code,
            models.VerifyCode.used.is_(False),
        )
        .order_by(models.VerifyCode.created_at.desc())
        .first()
    )
    if not row:
        return False
    if row.expires_at < datetime.utcnow():
        return False
    return True


def _mark_code_used(db: Session, email: str, purpose: str, code: str):
    row = (
        db.query(models.VerifyCode)
        .filter(
            models.VerifyCode.email == email,
            models.VerifyCode.purpose == purpose,
            models.VerifyCode.code == code,
            models.VerifyCode.used.is_(False),
        )
        .order_by(models.VerifyCode.created_at.desc())
        .first()
    )
    if row:
        row.used = True
        db.commit()


@router.post("/register", response_model=schemas.SendCodeOut)
def register(user_in: schemas.UserCreate, request: Request, db: Session = Depends(get_db)):
    _check_limit(_register_limiter, f"reg:{_client_ip(request)}")
    if not user_in.email:
        raise HTTPException(status_code=400, detail="Для регистрации нужен email")

    email = str(user_in.email).lower()
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    referred_by = None
    if user_in.referral_code:
        code = str(user_in.referral_code).strip().upper()
        referred_by = (
            db.query(models.User)
            .filter(models.User.referral_code == code)
            .first()
        )
        if not referred_by:
            raise HTTPException(status_code=400, detail="Неверный код приглашения")

    username = None
    if user_in.username:
        username = validate_username(user_in.username)
        if username:
            taken = db.query(models.User).filter(models.User.username == username).first()
            if taken:
                raise HTTPException(status_code=400, detail="Этот тег уже занят")

    user = models.User(
        name=user_in.name,
        username=username,
        email=email,
        phone=user_in.phone,
        password_hash=auth.hash_password(user_in.password),
        birth_date=user_in.birth_date,
        gender=user_in.gender,
        status=models.UserStatus.pending,  # активируется после ввода кода
        is_verified=False,
        referral_code=auth.generate_referral_code(),
        referred_by_id=referred_by.id if referred_by else None,
    )
    db.add(user)
    db.commit()

    code = _issue_code(db, email, "register")
    sent = mailer.send_code(email, code, "register")
    if sent:
        return schemas.SendCodeOut(email=email)
    return schemas.SendCodeOut(email=email, dev_code=code)


@router.post("/verify-registration", response_model=schemas.Token)
def verify_registration(
    payload: schemas.VerifyCodeIn, request: Request, db: Session = Depends(get_db)
):
    _check_limit(_code_limiter, f"verify:{_client_ip(request)}")
    email = str(payload.email).lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.status != models.UserStatus.pending:
        raise HTTPException(status_code=400, detail="Аккаунт уже подтверждён")

    if not _code_is_valid(db, email, "register", payload.code):
        raise HTTPException(status_code=400, detail="Неверный или просроченный код")

    _mark_code_used(db, email, "register", payload.code)
    user.status = models.UserStatus.active
    user.is_verified = True

    # Начисляем реферальные бонусы, если пользователь пришёл по коду
    if user.referred_by_id:
        inviter = db.query(models.User).filter(models.User.id == user.referred_by_id).first()
        if inviter:
            inviter.referral_count += 1
            inviter.credits = (inviter.credits or 0) + REFERRAL_INVITE_BONUS
            user.credits = (user.credits or 0) + REFERRAL_BONUS
            db.add(models.Notification(
                user_id=inviter.id,
                title="Друг по твоему коду",
                body="Кто-то зарегистрировался по твоему приглашению. Бонус начислен!",
            ))
    db.commit()

    token = auth.create_access_token({"sub": user.id})
    return schemas.Token(access_token=token)


@router.post("/resend-code", response_model=schemas.SendCodeOut)
def resend_code(payload: schemas.ResendCodeIn, request: Request, db: Session = Depends(get_db)):
    """Повторная отправка кода (purpose: register | reset_password)."""
    _check_limit(_code_limiter, f"resend:{_client_ip(request)}")
    email = str(payload.email).lower()
    purpose = payload.purpose
    if purpose not in ("register", "reset_password"):
        raise HTTPException(status_code=400, detail="Неизвестный purpose")

    user = db.query(models.User).filter(models.User.email == email).first()
    if purpose == "register":
        if not user or user.status != models.UserStatus.pending:
            raise HTTPException(status_code=400, detail="Аккаунт уже подтверждён или не найден")
    else:
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

    code = _issue_code(db, email, purpose)
    sent = mailer.send_code(email, code, purpose)
    if sent:
        return schemas.SendCodeOut(email=email)
    return schemas.SendCodeOut(email=email, dev_code=code)


@router.post("/request-password-reset", response_model=schemas.SendCodeOut)
def request_password_reset(
    payload: schemas.EmailIn, request: Request, db: Session = Depends(get_db)
):
    _check_limit(_reset_limiter, f"reset:{_client_ip(request)}")
    email = str(payload.email).lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    code = _issue_code(db, email, "reset_password")
    sent = mailer.send_code(email, code, "reset_password")
    if sent:
        return schemas.SendCodeOut(email=email)
    return schemas.SendCodeOut(email=email, dev_code=code)


@router.post("/reset-password")
def reset_password(payload: schemas.ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    _check_limit(_reset_limiter, f"reset2:{_client_ip(request)}")
    email = str(payload.email).lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if not _code_is_valid(db, email, "reset_password", payload.code):
        raise HTTPException(status_code=400, detail="Неверный или просроченный код")

    _mark_code_used(db, email, "reset_password", payload.code)
    user.password_hash = auth.hash_password(payload.new_password)
    db.commit()
    return {"message": "Пароль изменён"}


@router.post("/login", response_model=schemas.Token)
def login(credentials: schemas.UserLogin, request: Request, db: Session = Depends(get_db)):
    _check_limit(_login_limiter, f"login:{_client_ip(request)}")
    query = db.query(models.User)
    user = None
    if credentials.email:
        user = query.filter(models.User.email == str(credentials.email).lower()).first()
    elif credentials.phone:
        user = query.filter(models.User.phone == credentials.phone).first()

    if not user or not auth.verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if user.status == models.UserStatus.pending:
        raise HTTPException(
            status_code=403,
            detail="Email не подтверждён. Проверь почту и введи код из письма",
        )

    token = auth.create_access_token({"sub": user.id})
    return schemas.Token(access_token=token)
