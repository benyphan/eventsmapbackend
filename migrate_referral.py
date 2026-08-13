"""Однократная миграция: добавить реферальные поля в users и раздать коды."""
import os
import random
import string
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/events_db",
)

ALPHABET = "".join(ch for ch in (string.ascii_uppercase + string.digits) if ch not in "O0I1")


def gen_code(existing):
    while True:
        code = "".join(random.SystemRandom().choice(ALPHABET) for _ in range(8))
        if code not in existing:
            return code


def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS referral_code VARCHAR UNIQUE,
        ADD COLUMN IF NOT EXISTS referred_by_id UUID REFERENCES users(id),
        ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS credits INTEGER DEFAULT 0
    """)
    print("columns ok")

    cur.execute("SELECT id FROM users WHERE referral_code IS NOT NULL")
    used = {r["id"]: None for r in cur.fetchall()}
    cur.execute("SELECT referral_code FROM users WHERE referral_code IS NOT NULL")
    existing_codes = {r["referral_code"] for r in cur.fetchall()}

    cur.execute("SELECT id, referral_code FROM users")
    for row in cur.fetchall():
        if row["referral_code"]:
            continue
        code = gen_code(existing_codes)
        existing_codes.add(code)
        cur.execute("UPDATE users SET referral_code = %s WHERE id = %s", (code, row["id"]))
        print("set code for", row["id"])

    conn.commit()
    cur.close()
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
