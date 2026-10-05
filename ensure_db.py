#!/usr/bin/env python
"""Create the configured PostgreSQL database if it does not exist.

Run at container startup so `docker compose up` works against the PostgreSQL
server (e.g. AWS RDS) without a manual step. Connects to the `postgres`
maintenance database (always present) and creates the app database named by
`DB_NAME` / `DATABASE_URL`.
"""

import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

import psycopg2
from django.conf import settings
from psycopg2 import sql

db = settings.DATABASES["default"]

if "postgresql" not in db.get("ENGINE", ""):
    print("PostgreSQL kullanilmiyor, veritabani olusturma atlandi.")
    sys.exit(0)

name = db["NAME"]
sslmode = (db.get("OPTIONS") or {}).get("sslmode", "prefer")

conn = None
for attempt in range(30):
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=db["USER"],
            password=db["PASSWORD"],
            host=db["HOST"],
            port=db["PORT"] or 5432,
            connect_timeout=5,
            sslmode=sslmode,
        )
        break
    except psycopg2.OperationalError as exc:
        if attempt == 29:
            raise
        print(f"PostgreSQL hazir degil, tekrar deneniyor ({attempt + 1}/30)...")
        time.sleep(2)

conn.autocommit = True
try:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cur.fetchone():
            print(f"Veritabani '{name}' zaten mevcut.")
        else:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(name), sql.Identifier(db["USER"])
                )
            )
            print(f"Veritabani '{name}' olusturuldu.")
finally:
    conn.close()
