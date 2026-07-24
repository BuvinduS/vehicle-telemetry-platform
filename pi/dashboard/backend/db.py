# pi/dashboard/db.py
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from psycopg2 import pool as pg_pool

from . import config

_pool: pg_pool.SimpleConnectionPool | None = None
DISPLAY_TZINFO = ZoneInfo(config.DISPLAY_TZ)


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    _pool = pg_pool.SimpleConnectionPool(
        minconn,
        maxconn,
        host=config.PG_HOST,
        port=config.PG_PORT,
        dbname=config.PG_DB,
        user=config.PG_USER,
        password=config.PG_PASS,
    )


def close_pool() -> None:
    if _pool is not None:
        _pool.closeall()


@contextmanager
def get_conn():
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() at startup")
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)


def to_display_tz(dt):
    """Convert a TIMESTAMPTZ value (UTC-aware from psycopg2) to DISPLAY_TZ
    for API responses. Storage stays UTC — this is display-layer only,
    per architecture.md §3.8."""
    if dt is None:
        return None
    return dt.astimezone(DISPLAY_TZINFO)