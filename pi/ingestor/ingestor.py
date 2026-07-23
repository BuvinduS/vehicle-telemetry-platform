"""
pi/ingestor/ingestor.py

Subscribes to telemetry/vehicle/obd and telemetry/vehicle/imu, merges the two
streams by a time-window match, and writes rows to TimescaleDB.

Session-decoupled per architecture.md §3.3: no session_id is required, read,
or written here. Sessions are pure metadata rows managed by the FastAPI
bridge; this ingestor doesn't know or care whether one is "open."

node_id: left NULL on every insert. Single-node assumed (architecture.md §4);
the column exists (§3.9) but populating it is out of scope for this chat.

Merge pattern (mqtt-topics.md): OBD and IMU are independent publishers on
separate topics. Buffer both, match by a time window (MERGE_WINDOW), and
flush a row when either:
  (a) a matching pair is found within the window, or
  (b) the older buffered message ages out of the window with no match
      (written as a partial row rather than dropped).

Threading note: paho-mqtt's loop_start() runs network I/O (and therefore
on_message -> merger.add_obd/add_imu) on its OWN background thread, while
main()'s flush loop (merger.age_out/drain) runs on the main thread. These
are two different threads touching the same buffers, so Merger uses an
internal lock around every buffer access.
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import paho.mqtt.client as mqtt
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ingestor")

# ── Config (env-driven, no hardcoded values per project convention) ────────
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

PG_HOST = os.environ.get("TIMESCALEDB_HOST", "localhost")
PG_PORT = int(os.environ.get("TIMESCALEDB_PORT", "5433"))
PG_DB = os.environ.get("TIMESCALEDB_DB", "telemetry")
PG_USER = os.environ.get("TIMESCALEDB_USER", "analytics")
PG_PASS = os.environ.get("TIMESCALEDB_PASSWORD", "analytics")

MERGE_WINDOW = float(os.environ.get("MERGE_WINDOW", "0.5"))  # seconds
FLUSH_INTERVAL = float(os.environ.get("FLUSH_INTERVAL", "1.0"))  # seconds
BATCH_SIZE = int(os.environ.get("INGEST_BATCH_SIZE", "50"))

CONNECT_RETRY_DELAY = float(os.environ.get("CONNECT_RETRY_DELAY", "3.0"))  # seconds

TOPIC_OBD = "telemetry/vehicle/obd"
TOPIC_IMU = "telemetry/vehicle/imu"


@dataclass
class PendingObd:
    ts: float
    speed_kmh: Optional[float] = None
    rpm: Optional[float] = None
    throttle_pct: Optional[float] = None
    coolant_temp_c: Optional[float] = None
    engine_load_pct: Optional[float] = None


@dataclass
class PendingImu:
    ts: float
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None


class Merger:
    """Buffers OBD/IMU messages and yields merged (or partial) rows.

    Thread-safe: add_obd/add_imu are called from the MQTT network thread
    (via loop_start()); age_out/drain are called from main()'s flush loop
    on the main thread. All buffer access goes through self._lock.
    """

    def __init__(self, window: float):
        self.window = window
        self._lock = threading.Lock()
        self._obd_buf: list[PendingObd] = []
        self._imu_buf: list[PendingImu] = []
        self._out: list[dict] = []

    def add_obd(self, msg: PendingObd) -> None:
        with self._lock:
            self._obd_buf.append(msg)
            self._try_match()

    def add_imu(self, msg: PendingImu) -> None:
        with self._lock:
            self._imu_buf.append(msg)
            self._try_match()

    def _try_match(self) -> None:
        # Caller must hold self._lock.
        # Greedy nearest-match within window; buffers are small (sub-second
        # of messages at 5-10Hz), so O(n*m) here is not a concern.
        self._obd_buf.sort(key=lambda m: m.ts)
        self._imu_buf.sort(key=lambda m: m.ts)

        matched_obd_idx = set()
        matched_imu_idx = set()

        for i, o in enumerate(self._obd_buf):
            best_j, best_dt = None, None
            for j, im in enumerate(self._imu_buf):
                if j in matched_imu_idx:
                    continue
                dt = abs(o.ts - im.ts)
                if dt <= self.window and (best_dt is None or dt < best_dt):
                    best_j, best_dt = j, dt
            if best_j is not None:
                im = self._imu_buf[best_j]
                self._out.append(self._row(o, im))
                matched_obd_idx.add(i)
                matched_imu_idx.add(best_j)

        self._obd_buf = [o for i, o in enumerate(self._obd_buf) if i not in matched_obd_idx]
        self._imu_buf = [im for j, im in enumerate(self._imu_buf) if j not in matched_imu_idx]

    def age_out(self, now: float) -> None:
        """Flush anything older than the window as a partial row rather than
        dropping it — per mqtt-topics.md's documented fallback behaviour."""
        with self._lock:
            still_obd = []
            for o in self._obd_buf:
                if now - o.ts > self.window:
                    self._out.append(self._row(o, None))
                else:
                    still_obd.append(o)
            self._obd_buf = still_obd

            still_imu = []
            for im in self._imu_buf:
                if now - im.ts > self.window:
                    self._out.append(self._row(None, im))
                else:
                    still_imu.append(im)
            self._imu_buf = still_imu

    def drain(self) -> list[dict]:
        with self._lock:
            out, self._out = self._out, []
            return out

    @staticmethod
    def _row(o: Optional[PendingObd], im: Optional[PendingImu]) -> dict:
        ts = o.ts if o else im.ts
        return {
            "time": ts,
            "speed_kmh": o.speed_kmh if o else None,
            "rpm": o.rpm if o else None,
            "throttle_pct": o.throttle_pct if o else None,
            "coolant_temp_c": o.coolant_temp_c if o else None,
            "engine_load_pct": o.engine_load_pct if o else None,
            "accel_x": im.accel_x if im else None,
            "accel_y": im.accel_y if im else None,
            "accel_z": im.accel_z if im else None,
        }


merger = Merger(MERGE_WINDOW)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        log.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
        client.subscribe(TOPIC_OBD)
        client.subscribe(TOPIC_IMU)
    else:
        log.error("MQTT connect failed, rc=%s", rc)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning("Dropping unparseable message on %s: %s", msg.topic, e)
        return

    if "ts" not in payload:
        log.warning("Dropping message on %s with no 'ts' field", msg.topic)
        return

    if msg.topic == TOPIC_OBD:
        # NOTE: advanced mode still carries the core fields (mqtt-topics.md:
        # advanced payload = normal payload + all_pids). Only all_pids itself
        # is excluded from persistence (schema-reference.md) — the core
        # telemetry from an advanced-mode message is still real data and
        # still gets written, same as normal mode. Dropping the whole
        # message here would silently create gaps in any session that
        # included advanced-mode viewing.
        merger.add_obd(
            PendingObd(
                ts=payload["ts"],
                speed_kmh=payload.get("speed_kmh"),
                rpm=payload.get("rpm"),
                throttle_pct=payload.get("throttle_pct"),
                coolant_temp_c=payload.get("coolant_temp_c"),
                engine_load_pct=payload.get("engine_load_pct"),
            )
        )
    elif msg.topic == TOPIC_IMU:
        merger.add_imu(
            PendingImu(
                ts=payload["ts"],
                accel_x=payload.get("accel_x"),
                accel_y=payload.get("accel_y"),
                accel_z=payload.get("accel_z"),
            )
        )


def write_rows(conn, rows: list[dict]) -> None:
    if not rows:
        return
    cols = [
        "time", "speed_kmh", "rpm", "throttle_pct", "coolant_temp_c",
        "engine_load_pct", "accel_x", "accel_y", "accel_z",
    ]
    values = [
        (
            _to_ts(r["time"]), r["speed_kmh"], r["rpm"], r["throttle_pct"],
            r["coolant_temp_c"], r["engine_load_pct"], r["accel_x"],
            r["accel_y"], r["accel_z"],
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"INSERT INTO telemetry ({', '.join(cols)}) VALUES %s",
            values,
        )
    conn.commit()
    log.info("Wrote %d row(s)", len(rows))


def _to_ts(epoch_seconds: float):
    import datetime
    return datetime.datetime.fromtimestamp(epoch_seconds, tz=datetime.timezone.utc)


def _connect_db():
    while True:
        try:
            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS,
            )
            log.info("Connected to TimescaleDB at %s:%s/%s", PG_HOST, PG_PORT, PG_DB)
            return conn
        except psycopg2.OperationalError as e:
            log.warning("DB connect failed (%s), retrying in %.1fs", e, CONNECT_RETRY_DELAY)
            time.sleep(CONNECT_RETRY_DELAY)


def _connect_mqtt():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            return client
        except (ConnectionRefusedError, OSError) as e:
            log.warning("MQTT connect failed (%s), retrying in %.1fs", e, CONNECT_RETRY_DELAY)
            time.sleep(CONNECT_RETRY_DELAY)


def main():
    conn = _connect_db()
    client = _connect_mqtt()
    client.loop_start()

    try:
        while True:
            time.sleep(FLUSH_INTERVAL)
            merger.age_out(time.time())
            rows = merger.drain()
            if rows:
                write_rows(conn, rows)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        client.loop_stop()
        client.disconnect()
        conn.close()


if __name__ == "__main__":
    main()