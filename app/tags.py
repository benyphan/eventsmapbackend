import re

from fastapi import HTTPException

USERNAME_MIN_LENGTH = 5
USERNAME_RE = re.compile(r"^[a-z0-9_]+$")

# Системные теги, которые нельзя занимать пользователям
RESERVED_USERNAMES = {"admin", "administrator", "administator"}

# Запрещённые слова (мат и грубые оскорбления) — проверка по подстроке
FORBIDDEN_USERNAME_PARTS = [
    "хуй", "пизд", "бля", "ебан", "ебал", "ебат", "гандон", "мудак",
    "пидор", "шлюх", "шлюш", "сука", "тварь", "залуп", "петух",
    "хуес", "дроч", "сосат", "отсос", "вагин", "влагал",
    "fuck", "shit", "bitch", "asshole", "cunt", "nigg", "dick",
]


def normalize_username(raw) -> str | None:
    """Возвращает нормализованный тег (без @, нижний регистр) или None."""
    if raw is None:
        return None
    username = str(raw).strip().lower().lstrip("@")
    if not username:
        return None
    return username


def validate_username(raw) -> str | None:
    """Валидация тега. Бросает HTTPException(400) при нарушении правил."""
    username = normalize_username(raw)
    if username is None:
        return None
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="Тег может содержать только латинские буквы, цифры и нижнее подчёркивание",
        )
    if len(username) < USERNAME_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Тег должен содержать минимум {USERNAME_MIN_LENGTH} символов",
        )
    if username in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail="Этот тег занят системой")
    for word in FORBIDDEN_USERNAME_PARTS:
        if word in username:
            raise HTTPException(status_code=400, detail="Тег содержит запрещённое слово")
    return username
