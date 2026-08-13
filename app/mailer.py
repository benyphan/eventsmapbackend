import os
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

# Настройки SMTP. По умолчанию — Яндекс.Почта (smtp.yandex.ru:465).
# Задаются переменными окружения:
#   SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / EMAIL_FROM
# Если SMTP_USER не задан — включён dev-режим: письма не уходят,
# код печатается в лог сервера и возвращается в ответе API (dev_code).
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)

SUBJECTS = {
    "register": "MLocation — код подтверждения",
    "reset_password": "MLocation — восстановление пароля",
}
BODIES = {
    "register": "Ваш код подтверждения: {code}. Он действителен 10 минут.",
    "reset_password": "Ваш код для восстановления пароля: {code}. Он действителен 10 минут.",
}


def generate_code() -> str:
    return str(random.randint(100000, 999999))


def smtp_enabled() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


def send_code(email: str, code: str, purpose: str) -> bool:
    """Отправляет код на почту. Возвращает True, если письмо реально ушло,
    False — если SMTP не настроен (dev-режим, код только в логе)."""
    if not smtp_enabled():
        print(f"[MAIL-DEV] {purpose} code for {email}: {code}")
        return False

    subject = SUBJECTS.get(purpose, SUBJECTS["register"])
    body = BODIES.get(purpose, BODIES["register"]).format(code=code)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[MAIL-ERROR] {e}")
        return False
