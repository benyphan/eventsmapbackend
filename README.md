# Events Map API (FastAPI)

## Запуск локально

1. Установи PostgreSQL с расширением PostGIS.
   ```sql
   CREATE DATABASE events_db;
   \c events_db
   CREATE EXTENSION postgis;
   ```

2. Создай виртуальное окружение и поставь зависимости:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Настрой переменные окружения (или создай `.env` и подгрузи через python-dotenv):
   ```
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/events_db
   SECRET_KEY=замени-на-длинную-случайную-строку
   ```

4. Запусти сервер:
   ```bash
   uvicorn app.main:app --reload
   ```

5. Открой документацию API (генерируется автоматически):
   ```
   http://localhost:8000/docs
   ```

## Структура проекта

```
backend/
  app/
    main.py         — точка входа, роуты подключаются здесь
    database.py      — подключение к БД
    models.py         — таблицы (User, Event, EventCriteria, EventParticipant, Chat, Message, Report)
    schemas.py         — Pydantic-схемы запросов/ответов
    auth.py            — JWT-авторизация, хэширование паролей
    routers/
      auth.py           — /auth/register, /auth/login
      users.py           — /users/me
      events.py           — /events (список рядом, создание, заявки на участие)
      admin.py             — /admin/events, /admin/users (только role=admin/moderator)
  requirements.txt
```

## Как сделать первого админа

После регистрации через `/auth/register` зайди в БД и вручную поменяй роль:
```sql
UPDATE users SET role = 'admin' WHERE email = 'твой@email.com';
```

## Что дальше добавить

- Alembic-миграции вместо `Base.metadata.create_all`
- Загрузку файлов (фото профиля/события) в S3-совместимое хранилище
- WebSocket-чат (python-socketio) с шифрованием сообщений
- Rate-limiting (например, через `slowapi`)
- Пуш-уведомления (Firebase Cloud Messaging)
