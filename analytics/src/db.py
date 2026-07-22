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

# Display timezone — the DB stores everything as UTC internally
# (TIMESTAMPTZ), which is correct and shouldn't change. This is purely
# about what query() hands back for display/plotting, so notebooks,
# Grafana (set to the same tz in its dashboard settings), and DBeaver
# (already showing local time) all agree on wall-clock time.
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "Asia/Colombo")


def get_engine():
    """Return the shared SQLAlchemy engine for the analytics dev DB."""
    return _engine


def query(sql: str, params=None) -> pd.DataFrame:
    """Run a query and return the result as a DataFrame, with any
    datetime columns converted to DISPLAY_TZ for consistent display
    across notebooks/Grafana/DBeaver."""
    df = pd.read_sql(sql, _engine, params=params)
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            if df[col].dt.tz is None:
                df[col] = df[col].dt.tz_localize("UTC")
            df[col] = df[col].dt.tz_convert(DISPLAY_TZ)
    return df