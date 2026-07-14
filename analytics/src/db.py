"""
Connection helper for the analytics/ dev TimescaleDB.

Reads connection params from environment variables (loaded via .env if
present), falling back to the defaults baked into docker-compose.yml so
this works out of the box against the local dev container with zero config.
"""
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5433"),
    "dbname": os.environ.get("DB_NAME", "telemetry"),
    "user": os.environ.get("DB_USER", "analytics"),
    "password": os.environ.get("DB_PASSWORD", "analytics"),
}


def get_connection():
    """Open a new psycopg2 connection to the analytics dev DB."""
    return psycopg2.connect(**DB_CONFIG)


def query(sql: str, params=None) -> pd.DataFrame:
    """Run a query and return the result as a DataFrame. Opens and closes
    its own connection — fine for exploratory notebook use; not meant for
    high-frequency calls."""
    with get_connection() as conn:
        return pd.read_sql(sql, conn, params=params)