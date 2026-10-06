"""Accès à PostgreSQL / PostGIS (SQLAlchemy Core, requêtes SQL explicites)."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.settings import ROOT, reglages


@lru_cache
def moteur() -> Engine:
    return create_engine(reglages().database_url, pool_pre_ping=True, future=True,
                         connect_args={"connect_timeout": 5})


@contextmanager
def transaction():
    """Une transaction : validée en sortie normale, annulée en cas d'exception."""
    with moteur().begin() as cx:
        yield cx


def appliquer_schema(cx: Connection | None = None) -> None:
    sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    if cx is None:
        with transaction() as c:
            c.exec_driver_sql(sql)
    else:
        cx.exec_driver_sql(sql)


def journaliser(cx: Connection, type_: str, message: str) -> None:
    cx.execute(text("INSERT INTO journal (type, message) VALUES (:t, :m)"), {"t": type_, "m": message[:2000]})
