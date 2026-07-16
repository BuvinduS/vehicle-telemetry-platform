-- Ported from schema-reference.md (vehicle-analytics-dashboard feasibility project).
-- Runs automatically via docker-entrypoint-initdb.d on first container start.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS drivers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    driver_id   TEXT REFERENCES drivers(id),
    started_at  TIMESTAMPTZ DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS telemetry (
    time                TIMESTAMPTZ     NOT NULL,
    session_id          TEXT            REFERENCES sessions(id),
    speed_kmh           REAL,
    rpm                 REAL,
    throttle_pct        REAL,
    coolant_temp_c      REAL,
    engine_load_pct     REAL,
    accel_x             REAL,
    accel_y             REAL,
    accel_z             REAL,
    latitude            REAL,
    longitude           REAL
);

SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1min
WITH (timescaledb.continuous) AS
    SELECT
        time_bucket('1 minute', time) AS bucket,
        session_id,
        AVG(speed_kmh)          AS avg_speed,
        MAX(speed_kmh)          AS max_speed,
        AVG(rpm)                AS avg_rpm,
        AVG(throttle_pct)       AS avg_throttle,
        AVG(engine_load_pct)    AS avg_load,
        MAX(ABS(accel_x))       AS max_accel_x,
        MAX(ABS(accel_y))       AS max_accel_y
    FROM telemetry
    GROUP BY bucket, session_id
WITH NO DATA;

-- Keep telemetry_1min current automatically — without this, new rows
-- inserted into telemetry (whether from live ingestion or a manual
-- DBeaver import) won't appear here until refresh_continuous_aggregate
-- is called manually.
SELECT add_continuous_aggregate_policy('telemetry_1min',
  start_offset => INTERVAL '1 hour',
  end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');

INSERT INTO drivers (id, name) VALUES ('driver_a', 'Test Driver')
    ON CONFLICT DO NOTHING;

INSERT INTO sessions (id, driver_id, notes) VALUES ('mock_001', 'driver_a', 'Mock data session')
    ON CONFLICT DO NOTHING;

INSERT INTO sessions (id, driver_id, notes) VALUES ('live_001', 'driver_a', 'Live OBD session')
    ON CONFLICT DO NOTHING;