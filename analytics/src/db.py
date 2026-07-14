"""
Connection helper for the analytics/ dev TimescaleDB.

Reads connection params from environment variables (loaded via .env if
present), falling back to the defaults baked into docker-compose.yml so
this works out of the box against the local dev container with zero config.
"""
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5433"),
    "dbname": os.environ.get("DB_NAME", "telemetry"),
    "user": os.environ.get("DB_USER", "analytics"),
    "password": os.environ.get("DB_PASSWORD", "analytics"),
}

_DB_URL = (
    f"postgresql+psycopg2://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
    f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
)

# Module-level engine — SQLAlchemy engines are meant to be created once and
# reused (they manage their own connection pool internally), not recreated
# per query.
_engine = create_engine(_DB_URL)


def get_engine():
    """Return the shared SQLAlchemy engine for the analytics dev DB."""
    return _engine


def query(sql: str, params=None) -> pd.DataFrame:
    """Run a query and return the result as a DataFrame."""
    return pd.read_sql(sql, _engine, params=params)