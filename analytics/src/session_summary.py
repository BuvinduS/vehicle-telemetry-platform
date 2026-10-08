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
import numpy as np
from src.db import query

G = 9.80665             # m/s² per g; accel columns are stored in m/s²
MAX_GAP_S = 2.0         # row gaps longer than this are dropouts, not driving
IDLE_KMH = 1.0          # below this counts as stationary
LONG_AXIS = "accel_x"   # calibrated longitudinal axis — VERIFY (see below)
HARSH_ACCEL_G = 0.30    # +longitudinal beyond this = harsh acceleration
HARSH_BRAKE_G = -0.30   # -longitudinal beyond this = harsh braking


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

def _dt_seconds(df: pd.DataFrame) -> pd.Series:
    """Seconds since the previous row, with dropout gaps zeroed out.
    Integrating with real timestamp deltas (not an assumed rate) keeps
    distance/idle-time honest when row density varies; capping at
    MAX_GAP_S stops a dropout from adding phantom distance."""
    dt = df["time"].diff().dt.total_seconds()
    return dt.where((dt > 0) & (dt <= MAX_GAP_S), 0.0).fillna(0.0)


def _count_events(mask: pd.Series) -> int:
    """Count contiguous runs of True (rising edges), so one long hard
    brake is one event, not one per row."""
    return int((mask & ~mask.shift(fill_value=False)).sum())


def best_time_to_speed(df: pd.DataFrame, target_kmh: float,
                       start_kmh: float = 2.0) -> float | None:
    """Fastest standstill -> target_kmh time in the session, or None.
    Tracks the most recent moment at/below start_kmh; the clock restarts
    on any later standstill or any data gap. Doesn't reject runs that
    ease off mid-way — fine for a demo stat."""
    t_start, prev_t, best = None, None, None
    for t, v in zip(df["time"], df["speed_kmh"]):
        if pd.isna(v):
            continue
        if prev_t is not None and (t - prev_t).total_seconds() > MAX_GAP_S:
            t_start = None
        prev_t = t
        if v <= start_kmh:
            t_start = t
        elif t_start is not None and v >= target_kmh:
            elapsed = (t - t_start).total_seconds()
            best = elapsed if best is None else min(best, elapsed)
            t_start = None
    return best


def speed_trace(df: pd.DataFrame, points: int = 60) -> list[dict]:
    """Downsampled speed series for the dashboard sparkline."""
    s = df[["time", "speed_kmh"]].dropna()
    if len(s) > points:
        s = s.iloc[np.linspace(0, len(s) - 1, points).astype(int)]
    return [{"t": t.isoformat(), "v": round(float(v), 1)}
            for t, v in zip(s["time"], s["speed_kmh"])]

def summarize_session(df: pd.DataFrame, session_id: str) -> dict:
    """Compute summary stats for a single session's telemetry DataFrame.

    Returns a flat dict — one row of a summary table. NaN-safe: uses
    pandas' skipna-by-default aggregations, so missing PID reads (nulls)
    don't blow up the calculation, just get excluded from that stat.
    """
    if df.empty:
        return {"session_id": session_id, "row_count": 0}

    dt = _dt_seconds(df)
    v_ms = df["speed_kmh"] / 3.6
    distance_km = ((v_ms + v_ms.shift()) / 2 * dt).sum() / 1000  # trapezoid

    has_speed = df["speed_kmh"].notna()
    tracked_s = dt[has_speed].sum()
    idle_s = dt[has_speed & (df["speed_kmh"] < IDLE_KMH)].sum()

    long_g = df[LONG_AXIS] / G

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
        "distance_km": distance_km,
        "idle_pct": 100 * idle_s / tracked_s if tracked_s > 0 else None,
        "peak_g": float(np.hypot(df["accel_x"], df["accel_y"]).max() / G),
        "harsh_accel_count": _count_events(long_g > HARSH_ACCEL_G),
        "harsh_brake_count": _count_events(long_g < HARSH_BRAKE_G),
        "best_0_60_s": best_time_to_speed(df, 60),
    }


def summarize_all_sessions() -> pd.DataFrame:
    """Convenience wrapper: summary stats for every session with data."""
    sessions = list_sessions()
    rows = []
    for session_id in sessions.loc[sessions["row_count"] > 0, "session_id"]:
        df = load_session_telemetry(session_id)
        rows.append(summarize_session(df, session_id))
    return pd.DataFrame(rows)