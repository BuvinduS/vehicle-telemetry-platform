"""
Per-session summary statistics — average/max speed, RPM/throttle profile,
peak lateral/longitudinal G.

Deliberately a plain module, not notebook-only logic: if this ever
graduates into a scheduled Pi service (per architecture.md's convention
for analysis logic that matures past exploratory), the functions here
are what that service would import and call directly, with the notebook
staying a thin wrapper around them.
"""
import pandas as pd

from src.db import query


def list_sessions() -> pd.DataFrame:
    """All sessions with a row count, computed via time-range join
    rather than a stored session_id — this is the query pattern from
    architecture.md §3.3 / schema-reference.md's planned schema, and
    works whether or not telemetry.session_id still exists in the
    table (it's simply not referenced)."""
    return query(
        """
        SELECT s.id AS session_id, s.driver_id, s.started_at, s.ended_at,
               s.notes, COUNT(t.time) AS row_count
        FROM sessions s
        LEFT JOIN telemetry t
          ON t.time BETWEEN s.started_at AND COALESCE(s.ended_at, NOW())
        GROUP BY s.id, s.driver_id, s.started_at, s.ended_at, s.notes
        ORDER BY s.started_at;
        """
    )


def load_session_telemetry(session_id: str) -> pd.DataFrame:
    """Telemetry for one session, via time-range join against
    sessions.started_at/ended_at — NOT a session_id equality filter.
    An open session (ended_at IS NULL) is treated as covering up to
    NOW(), per architecture.md §3.3."""
    return query(
        """
        SELECT t.*
        FROM telemetry t
        JOIN sessions s
          ON t.time BETWEEN s.started_at AND COALESCE(s.ended_at, NOW())
        WHERE s.id = %(session_id)s
        ORDER BY t.time;
        """,
        params={"session_id": session_id},
    )


def summarize_session(df: pd.DataFrame, session_id: str) -> dict:
    """Compute summary stats for a single session's telemetry DataFrame.

    Returns a flat dict — one row of a summary table. NaN-safe: uses
    pandas' skipna-by-default aggregations, so missing PID reads (nulls)
    don't blow up the calculation, just get excluded from that stat.
    """
    if df.empty:
        return {"session_id": session_id, "row_count": 0}

    return {
        "session_id": session_id,
        "row_count": len(df),
        "duration_s": (df["time"].max() - df["time"].min()).total_seconds(),
        "avg_speed_kmh": df["speed_kmh"].mean(),
        "max_speed_kmh": df["speed_kmh"].max(),
        "avg_rpm": df["rpm"].mean(),
        "max_rpm": df["rpm"].max(),
        "avg_throttle_pct": df["throttle_pct"].mean(),
        "max_throttle_pct": df["throttle_pct"].max(),
        "avg_coolant_temp_c": df["coolant_temp_c"].mean(),
        "max_coolant_temp_c": df["coolant_temp_c"].max(),
        "avg_engine_load_pct": df["engine_load_pct"].mean(),
        "max_abs_accel_x": df["accel_x"].abs().max(),
        "max_abs_accel_y": df["accel_y"].abs().max(),
    }


def summarize_all_sessions() -> pd.DataFrame:
    """Convenience wrapper: summary stats for every session with data."""
    sessions = list_sessions()
    rows = []
    for session_id in sessions.loc[sessions["row_count"] > 0, "session_id"]:
        df = load_session_telemetry(session_id)
        rows.append(summarize_session(df, session_id))
    return pd.DataFrame(rows)