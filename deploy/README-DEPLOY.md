# EventsMap — деплой бэкенда на VPS (Ubuntu 22.04/24.04)

## Что нужно до деплоя

1. VPS (минимум 1 vCPU / 1 GB RAM). Варианты:
   - **Oracle Cloud Free Tier** — бесплатно (Always Free: 4 vCPU / 24 GB RAM).
   - Hetzner CX22 — ~€4/мес.
   - DigitalOcean $6/мес.
2. Домен (например `eventsmap.ru`), у DNS-провайдера создай A-запись:
   ```
   api   A   <IP-сервера>
   ```
3. SSH-доступ к серверу (root или sudo-пользователь).

## Копирование кода

```bash
scp -r C:/Users/user/Documents/Mlocation/backend/backend user@<IP>:/opt/eventsmap/backend
```

## Запуск деплоя

```bash
cd /opt/eventsmap/backend
sudo bash deploy.sh
```

Скрипт сам: поставит PostgreSQL+PostGIS, Python, nginx, certbot,
создаст базу, виртуальное окружение, systemd-сервис и HTTPS-сертификат.

## Что настроить вручную после

1. Отредактируй `/opt/eventsmap/backend/.env`:
   - `DATABASE_URL` — уже совпадает (postgres:postgres@localhost:5432/events_db)
   - `SECRET_KEY` — замени на длинную случайную строку
   - `SMTP_*` — уже настроены (Mail.ru) и переносятся с `backend/.env`
2. Перезапусти сервис: `sudo systemctl restart eventsmap`

## Полезные команды

```bash
sudo systemctl status eventsmap   # статус
sudo journalctl -u eventsmap -f   # логи в реальном времени
sudo systemctl restart eventsmap  # перезапуск
```
