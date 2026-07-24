# pi/dashboard/config.py
import os

PG_HOST = os.environ.get("TIMESCALEDB_HOST", "localhost")
PG_PORT = int(os.environ.get("TIMESCALEDB_PORT", "5433"))
PG_DB = os.environ.get("TIMESCALEDB_DB", "telemetry")
PG_USER = os.environ.get("TIMESCALEDB_USER", "analytics")
PG_PASS = os.environ.get("TIMESCALEDB_PASSWORD", "analytics")

# architecture.md §3.8 — storage stays UTC, every API response displays
# local time.
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "Asia/Colombo")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))