"""
Per-session summary statistics, pure Python (no pandas/numpy).

Port of analytics/session_summary.py's summarize_session()/speed_trace()
for the FastAPI backend, which deliberately doesn't depend on pandas.
Logic must stay in sync with the analytics version — check_parity below
is how that's verified.

Rows are tuples in COLUMNS order, ordered by time; SQL NULL -> None.
"""
import math

G = 9.80665             # m/s² per g; accel columns are stored in m/s²
MAX_GAP_S = 2.0         # row gaps longer than this are dropouts
IDLE_KMH = 1.0
HARSH_BRAKE_G = -0.30   # longitudinal axis is accel_x (sign verified)
HARSH_ACCEL_G = 0.30

COLUMNS = ("time", "speed_kmh", "rpm", "throttle_pct",
           "coolant_temp_c", "engine_load_pct", "accel_x", "accel_y")
_PID_FIELDS = COLUMNS[1:6]


def summarize(rows: list[tuple]) -> dict:
    if not rows:
        return {"row_count": 0}

    # per-field [sum, count, max], skipping None
    acc = {f: [0.0, 0, None] for f in _PID_FIELDS}
    first_t = last_t = None
    prev_t = prev_v = None          # prev row's time / speed (m/s)
    distance_m = tracked_s = idle_s = 0.0
    peak_ms2 = 0.0
    max_abs_x = max_abs_y = None
    brake_run = accel_run = False
    brakes = accels = 0
    t_start = prev_speed_t = best_0_60 = None

    for row in rows:
        t, speed, rpm, thr, cool, load, ax, ay = row

        if first_t is None:
            first_t = t
        last_t = t

        dt = (t - prev_t).total_seconds() if prev_t is not None else 0.0
        if not (0 < dt <= MAX_GAP_S):
            dt = 0.0

        for f, v in zip(_PID_FIELDS, (speed, rpm, thr, cool, load)):
            if v is not None:
                a = acc[f]
                a[0] += v
                a[1] += 1
                a[2] = v if a[2] is None else max(a[2], v)

        # distance (trapezoid) and idle share, both time-weighted
        v_ms = speed / 3.6 if speed is not None else None
        if v_ms is not None and prev_v is not None:
            distance_m += (v_ms + prev_v) / 2 * dt
        if speed is not None:
            tracked_s += dt
            if speed < IDLE_KMH:
                idle_s += dt

        # accelerometer: peak planar G, per-axis max, harsh-event runs
        if ax is not None:
            max_abs_x = abs(ax) if max_abs_x is None else max(max_abs_x, abs(ax))
        if ay is not None:
            max_abs_y = abs(ay) if max_abs_y is None else max(max_abs_y, abs(ay))
        if ax is not None and ay is not None:
            peak_ms2 = max(peak_ms2, math.hypot(ax, ay))
        long_g = ax / G if ax is not None else None
        braking = long_g is not None and long_g < HARSH_BRAKE_G
        accelerating = long_g is not None and long_g > HARSH_ACCEL_G
        brakes += braking and not brake_run
        accels += accelerating and not accel_run
        brake_run, accel_run = braking, accelerating

        # best standstill -> 60 km/h (clock restarts on standstill/gap)
        if speed is not None:
            if prev_speed_t is not None and \
                    (t - prev_speed_t).total_seconds() > MAX_GAP_S:
                t_start = None
            prev_speed_t = t
            if speed <= 2.0:
                t_start = t
            elif t_start is not None and speed >= 60:
                elapsed = (t - t_start).total_seconds()
                best_0_60 = elapsed if best_0_60 is None else min(best_0_60, elapsed)
                t_start = None

        prev_t, prev_v = t, v_ms

    def mean(f):
        s, n, _ = acc[f]
        return s / n if n else None

    return {
        "row_count": len(rows),
        "duration_s": (last_t - first_t).total_seconds(),
        "avg_speed_kmh": mean("speed_kmh"),
        "max_speed_kmh": acc["speed_kmh"][2],
        "avg_rpm": mean("rpm"),
        "max_rpm": acc["rpm"][2],
        "avg_throttle_pct": mean("throttle_pct"),
        "max_throttle_pct": acc["throttle_pct"][2],
        "avg_coolant_temp_c": mean("coolant_temp_c"),
        "max_coolant_temp_c": acc["coolant_temp_c"][2],
        "avg_engine_load_pct": mean("engine_load_pct"),
        "max_abs_accel_x": max_abs_x,
        "max_abs_accel_y": max_abs_y,
        "distance_km": distance_m / 1000,
        "idle_pct": 100 * idle_s / tracked_s if tracked_s > 0 else None,
        "peak_g": peak_ms2 / G,
        "harsh_accel_count": accels,
        "harsh_brake_count": brakes,
        "best_0_60_s": best_0_60,
    }


def speed_trace(rows: list[tuple], points: int = 60) -> list[dict]:
    """Downsampled speed series for the dashboard sparkline."""
    pts = [(r[0], r[1]) for r in rows if r[1] is not None]
    if len(pts) > points:
        step = (len(pts) - 1) / (points - 1)
        pts = [pts[round(i * step)] for i in range(points)]
    return [{"t": t.isoformat(), "v": round(v, 1)} for t, v in pts]