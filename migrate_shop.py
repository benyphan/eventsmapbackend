"""Миграция: таблицы shop_items/purchases/gifts + active_decoration + сид товаров."""
import os
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/events_db",
)


def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS active_decoration VARCHAR
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id UUID PRIMARY KEY,
            name VARCHAR NOT NULL,
            emoji VARCHAR,
            description TEXT,
            item_type VARCHAR NOT NULL DEFAULT 'decoration',
            price INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            item_id UUID NOT NULL REFERENCES shop_items(id),
            created_at TIMESTAMP DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gifts (
            id UUID PRIMARY KEY,
            from_user_id UUID NOT NULL REFERENCES users(id),
            to_user_id UUID NOT NULL REFERENCES users(id),
            item_id UUID NOT NULL REFERENCES shop_items(id),
            message TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
    """)

    cur.execute("SELECT count(*) AS c FROM shop_items")
    existing = cur.fetchone()["c"]
    if existing == 0:
        items = [
            # Украшения для профиля (~50 тыс. кредитов)
            ("Золотая рамка", "🖼️", "decoration", 50000, "Золотая рамка вокруг аватарки"),
            ("Корона", "👑", "decoration", 50000, "Корона над именем в профиле"),
            ("Неоновый ореол", "🔆", "decoration", 50000, "Светящийся ореол вокруг аватара"),
            ("Алмазный фон", "💎", "decoration", 50000, "Блестящий алмазный фон профиля"),
            ("Платиновый контур", "⚪", "decoration", 50000, "Платиновый контур аватарки"),
            ("Королевская мантия", "👑", "decoration", 150000, "Мантия + корона (особый статус)"),
            # Подарки другим пользователям
            ("Букет роз", "🌹", "gift", 50000, "Красивый букет алых роз"),
            ("Плюшевый мишка", "🧸", "gift", 50000, "Милота, которая растапливает сердце"),
            ("Шоколад ручной работы", "🍫", "gift", 50000, "Дорогой шоколад в подарочной упаковке"),
            ("Умная колонка", "🔊", "gift", 100000, "Современная колонка с голосовым ассистентом"),
            ("Кольцо с бриллиантом", "💍", "gift", 500000, "Самый дорогой подарок в каталоге"),
        ]
        for name, emoji, item_type, price, desc in items:
            cur.execute(
                "INSERT INTO shop_items (id, name, emoji, description, item_type, price, is_active)"
                " VALUES (%s, %s, %s, %s, %s, %s, TRUE)",
                (str(uuid.uuid4()), name, emoji, desc, item_type, price),
            )
        print("seeded", len(items), "items")
    else:
        print("shop_items already has", existing, "rows")

    conn.commit()
    cur.close()
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
