# pi/dashboard/backend/mqtt_bridge.py
"""
WebSocket-facing MQTT bridge — independent of pi/ingestor/ingestor.py.

Subscribes to the same telemetry/vehicle/obd and telemetry/vehicle/imu
topics as the ingestor (mqtt-topics.md: OBD and IMU are independent
publishers; this bridge does its own separate in-memory merge purely
for live WebSocket display, never touching TimescaleDB). Advanced-mode
all_pids payloads are forwarded straight through to connected clients,
never buffered/merged, since they're WS-only and never persisted
(schema-reference.md).
"""

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import paho.mqtt.client as mqtt

from . import config, db

log = logging.getLogger("mqtt_bridge")

TOPIC_OBD = "telemetry/vehicle/obd"
TOPIC_IMU = "telemetry/vehicle/imu"

MERGE_WINDOW = 0.5   # seconds — same convention as the ingestor
FLUSH_INTERVAL = 0.5  # seconds — tighter than the ingestor's 1.0s since this
                       # feeds a live UI, not a DB batch write
SESSION_POLL_INTERVAL = 3.0  # seconds


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


class BridgeMerger:
    """Same windowed nearest-match pattern as pi/ingestor's Merger.
    Thread-safe: add_obd/add_imu run on the MQTT thread, age_out/drain
    run from the asyncio flush task on the main event loop thread."""

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
        self._obd_buf.sort(key=lambda m: m.ts)
        self._imu_buf.sort(key=lambda m: m.ts)

        matched_obd, matched_imu = set(), set()
        for i, o in enumerate(self._obd_buf):
            best_j, best_dt = None, None
            for j, im in enumerate(self._imu_buf):
                if j in matched_imu:
                    continue
                dt = abs(o.ts - im.ts)
                if dt <= self.window and (best_dt is None or dt < best_dt):
                    best_j, best_dt = j, dt
            if best_j is not None:
                self._out.append(self._row(o, self._imu_buf[best_j]))
                matched_obd.add(i)
                matched_imu.add(best_j)

        self._obd_buf = [o for i, o in enumerate(self._obd_buf) if i not in matched_obd]
        self._imu_buf = [im for j, im in enumerate(self._imu_buf) if j not in matched_imu]

    def age_out(self, now: float) -> None:
        with self._lock:
            still_obd = []
            for o in self._obd_buf:
                (self._out.append(self._row(o, None)) if now - o.ts > self.window
                 else still_obd.append(o))
            self._obd_buf = still_obd

            still_imu = []
            for im in self._imu_buf:
                (self._out.append(self._row(None, im)) if now - im.ts > self.window
                 else still_imu.append(im))
            self._imu_buf = still_imu

    def drain(self) -> list[dict]:
        with self._lock:
            out, self._out = self._out, []
            return out

    @staticmethod
    def _row(o: Optional[PendingObd], im: Optional[PendingImu]) -> dict:
        ts = o.ts if o else im.ts
        return {
            "ts": ts,
            "speed_kmh": o.speed_kmh if o else None,
            "rpm": o.rpm if o else None,
            "throttle_pct": o.throttle_pct if o else None,
            "coolant_temp_c": o.coolant_temp_c if o else None,
            "engine_load_pct": o.engine_load_pct if o else None,
            "accel_x": im.accel_x if im else None,
            "accel_y": im.accel_y if im else None,
            "accel_z": im.accel_z if im else None,
        }


class ConnectionManager:
    """Tracks connected WebSocket clients and broadcasts JSON messages."""

    def __init__(self):
        self._clients: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        text = json.dumps(message)
        async with self._lock:
            dead = []
            for ws in self._clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    async def send_to(self, websocket, message: dict) -> None:
        await websocket.send_text(json.dumps(message))


manager = ConnectionManager()
merger = BridgeMerger(MERGE_WINDOW)


def _fetch_active_sessions() -> list[dict]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, driver_id, node_id, started_at, ended_at, notes
                FROM sessions WHERE ended_at IS NULL ORDER BY started_at
                """
            )
            rows = cur.fetchall()
    return [
        {
            "id": r[0], "name": r[1], "driver_id": r[2], "node_id": r[3],
            "started_at": db.to_display_tz(r[4]).isoformat(),
            "ended_at": None,
            "notes": r[6],
        }
        for r in rows
    ]


class MqttBridge:
    def __init__(self):
        self._client: Optional[mqtt.Client] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._session_task: Optional[asyncio.Task] = None

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("Bridge connected to MQTT broker at %s:%s", config.MQTT_HOST, config.MQTT_PORT)
            client.subscribe(TOPIC_OBD)
            client.subscribe(TOPIC_IMU)
        else:
            log.error("Bridge MQTT connect failed, rc=%s", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning("Bridge dropping unparseable message on %s: %s", msg.topic, e)
            return

        if "ts" not in payload:
            return

        if msg.topic == TOPIC_OBD:
            if payload.get("mode") == "advanced" and "all_pids" in payload:
                # WS-only, never persisted, never merged — forward immediately.
                self._schedule_broadcast({"type": "advanced_pids", "data": payload["all_pids"], "ts": payload["ts"]})
                return
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

    def _schedule_broadcast(self, message: dict) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(manager.broadcast(message), self._loop)

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(FLUSH_INTERVAL)
            merger.age_out(time.time())
            for row in merger.drain():
                await manager.broadcast({"type": "telemetry", "data": row})

    async def _session_loop(self):
        while True:
            try:
                sessions = await asyncio.to_thread(_fetch_active_sessions)
                await manager.broadcast({"type": "active_sessions", "data": sessions})
            except Exception as e:
                log.warning("Active-session poll failed: %s", e)
            await asyncio.sleep(SESSION_POLL_INTERVAL)

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
        self._client.loop_start()
        self._flush_task = loop.create_task(self._flush_loop())
        self._session_task = loop.create_task(self._session_loop())

    def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        if self._session_task:
            self._session_task.cancel()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()


bridge = MqttBridge()