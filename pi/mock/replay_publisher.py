#!/usr/bin/env python3
"""
replay_publisher.py

Plays back a previously-recorded telemetry session from TimescaleDB over
MQTT, re-stamping every row's `ts` to the current wall-clock time at the
moment it's published. Intended purely for demo/testing of the FastAPI
bridge + Next.js dashboard, the same way `ros2 bag play` re-stamps a
recorded bag onto live playback time.

DOES NOT WRITE TO THE DATABASE. This only reads rows once at startup,
then talks pure MQTT. As long as the ingestor (pi/ingestor) is NOT
running while this plays, nothing gets persisted — Mosquitto has no
persistence of its own for this purpose, and the FastAPI WebSocket
bridge is a separate, independent MQTT consumer (see mqtt-topics.md's
note on the ingestor and bridge being independent consumers of the same
fan-out). If the ingestor IS running, this will insert new rows as if
a real drive just happened — stop it first for pure playback.

Source data note: `telemetry` has no `session_id` column post-migration
(architecture.md §3.3) — rows are selected via the standard time-range
join against `sessions`, exactly like every other session-scoped query
in this project (schema-reference.md).

Config is entirely env-driven (project convention, lessons-learned.md /
architecture.md) with CLI overrides for the things you'll want to tweak
per playback run (session, speed, loop).

Usage:
    python replay_publisher.py --session-id real_obd_001
    python replay_publisher.py --session-id real_obd_001 --speed 2.0 --loop
    python replay_publisher.py --start "2026-07-20T09:00:00+05:30" --end "2026-07-20T09:15:00+05:30"

Environment variables:
    TIMESCALEDB_HOST      (default: localhost)
    TIMESCALEDB_PORT      (default: 5432)
    TIMESCALEDB_DB        (default: telemetry)
    TIMESCALEDB_USER      (default: postgres)
    TIMESCALEDB_PASSWORD  (default: analytics)
    MQTT_BROKER_HOST      (default: localhost)
    MQTT_BROKER_PORT      (default: 1883)
    MQTT_OBD_TOPIC        (default: telemetry/vehicle/obd)
    MQTT_IMU_TOPIC        (default: telemetry/vehicle/imu)
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
import paho.mqtt.client as mqtt


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class Config:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    mqtt_host: str
    mqtt_port: int
    obd_topic: str
    imu_topic: str


def load_config() -> Config:
    missing = []
    db_password = os.environ.get("TIMESCALEDB_PASSWORD", "analytics")
    if not db_password:
        missing.append("TIMESCALEDB_PASSWORD")
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    return Config(
        db_host=os.environ.get("TIMESCALEDB_HOST", "localhost"),
        db_port=int(os.environ.get("TIMESCALEDB_PORT", "5433")),
        db_name=os.environ.get("TIMESCALEDB_DB", "telemetry"),
        db_user=os.environ.get("TIMESCALEDB_USER", "analytics"),
        db_password=db_password,
        mqtt_host=os.environ.get("MQTT_BROKER_HOST", "localhost"),
        mqtt_port=int(os.environ.get("MQTT_BROKER_PORT", "1883")),
        obd_topic=os.environ.get("MQTT_OBD_TOPIC", "telemetry/vehicle/obd"),
        imu_topic=os.environ.get("MQTT_IMU_TOPIC", "telemetry/vehicle/imu"),
    )


# --------------------------------------------------------------------------
# Data fetch
# --------------------------------------------------------------------------

# Selects rows via the standard time-range join (architecture.md §3.3) when
# a session id is given, falling back to an explicit start/end window
# otherwise. Ordered by time — playback order matters, capture order does
# not need to.
SELECT_BY_SESSION = """
    SELECT t.time, t.speed_kmh, t.rpm, t.throttle_pct, t.coolant_temp_c,
           t.engine_load_pct, t.accel_x, t.accel_y, t.accel_z
    FROM telemetry t
    JOIN sessions s ON t.time BETWEEN s.started_at AND COALESCE(s.ended_at, NOW())
    WHERE s.id = %s
    ORDER BY t.time ASC;
"""

SELECT_BY_RANGE = """
    SELECT time, speed_kmh, rpm, throttle_pct, coolant_temp_c,
           engine_load_pct, accel_x, accel_y, accel_z
    FROM telemetry
    WHERE time BETWEEN %s AND %s
    ORDER BY time ASC;
"""


def fetch_rows(cfg: Config, session_id: Optional[str], start: Optional[str], end: Optional[str]):
    conn = psycopg2.connect(
        host=cfg.db_host, port=cfg.db_port, dbname=cfg.db_name,
        user=cfg.db_user, password=cfg.db_password,
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if session_id:
                cur.execute(SELECT_BY_SESSION, (session_id,))
            else:
                cur.execute(SELECT_BY_RANGE, (start, end))
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("No rows found for the given session/time range — nothing to play back.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(rows)} rows spanning "
          f"{rows[0]['time']} -> {rows[-1]['time']}.")
    return rows


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------

def build_payloads(row, now_ts: float):
    """
    Splits one merged `telemetry` row back into independent OBD and IMU
    payloads, matching the planned (session_id-free) MQTT shapes in
    mqtt-topics.md. `ts` is re-stamped to the current wall-clock time,
    NOT the original capture time — the whole point of playback is that
    it looks live to every downstream consumer.

    Nulls are passed through explicitly rather than omitted, per the
    project's "advertise null rather than omit" convention.
    """
    obd_payload = {
        "ts": now_ts,
        "mode": "normal",
        "speed_kmh": row["speed_kmh"],
        "rpm": row["rpm"],
        "throttle_pct": row["throttle_pct"],
        "coolant_temp_c": row["coolant_temp_c"],
        "engine_load_pct": row["engine_load_pct"],
    }
    imu_payload = {
        "ts": now_ts,
        "accel_x": row["accel_x"],
        "accel_y": row["accel_y"],
        "accel_z": row["accel_z"],
    }
    return obd_payload, imu_payload


# --------------------------------------------------------------------------
# Playback loop
# --------------------------------------------------------------------------

def play(cfg: Config, rows, speed: float, loop: bool):
    client = mqtt.Client()
    client.connect(cfg.mqtt_host, cfg.mqtt_port)
    client.loop_start()

    try:
        while True:
            prev_time = None
            for row in rows:
                if prev_time is not None:
                    delta = (row["time"] - prev_time).total_seconds()
                    sleep_for = max(0.0, delta / speed)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                prev_time = row["time"]

                now_ts = time.time()
                obd_payload, imu_payload = build_payloads(row, now_ts)

                client.publish(cfg.obd_topic, json.dumps(obd_payload))
                client.publish(cfg.imu_topic, json.dumps(imu_payload))

                readable = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
                print(f"[{readable}] published row (orig time {row['time']})")

            if not loop:
                break
            print("Reached end of playback window — looping.")
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        client.loop_stop()
        client.disconnect()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session-id", help="Session id to replay (time-range join against sessions).")
    parser.add_argument("--start", help="Explicit window start (ISO 8601), used if --session-id is omitted.")
    parser.add_argument("--end", help="Explicit window end (ISO 8601), used if --session-id is omitted.")
    parser.add_argument("--speed", type=float, default=1.0,
                         help="Playback speed multiplier. 1.0 = real-time pacing, 2.0 = 2x, 0.5 = half speed.")
    parser.add_argument("--loop", action="store_true", help="Loop playback indefinitely.")
    args = parser.parse_args()

    if not args.session_id and not (args.start and args.end):
        parser.error("Provide either --session-id or both --start and --end.")

    cfg = load_config()
    rows = fetch_rows(cfg, args.session_id, args.start, args.end)

    print(f"Publishing to {cfg.mqtt_host}:{cfg.mqtt_port} "
          f"[{cfg.obd_topic}, {cfg.imu_topic}] at {args.speed}x speed"
          f"{' (looping)' if args.loop else ''}.")
    print("Reminder: make sure the ingestor is NOT running, or this will "
          "write new rows to telemetry as if a real drive just happened.\n")

    play(cfg, rows, args.speed, args.loop)


if __name__ == "__main__":
    main()