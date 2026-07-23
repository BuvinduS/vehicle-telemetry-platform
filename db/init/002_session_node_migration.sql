-- Migration 002: session model redesign + multi-node identity
-- Implements architecture.md §3.3 and §3.9, schema-reference.md "Planned change"
--
-- Run this against the existing dev DB (vtp-analytics-db, port 5433) AFTER
-- 001_schema.sql has already created the original tables. Idempotent where
-- reasonably possible (IF EXISTS / IF NOT EXISTS), but this is a one-way
-- migration — no down-migration is provided, since telemetry.session_id's
-- data is fully recoverable from the time-range join it's being replaced by.

BEGIN;

-- ── 0. Drop the continuous aggregate first ──────────────────────────────
-- telemetry_1min's SELECT groups by session_id, so it hard-blocks the
-- ALTER TABLE ... DROP COLUMN session_id below ("other objects depend on
-- it") until it's gone. It's recreated in step 4 below, regrouped without
-- session_id — under the new model, session membership is a time-range
-- join, not something the aggregate can (or should) group by directly.
-- CASCADE also removes the associated refresh policy and the underlying
-- _timescaledb_internal._partial_view_2 / _direct_view_2 objects that
-- triggered this error.
DROP MATERIALIZED VIEW IF EXISTS telemetry_1min CASCADE;

-- ── 1. Multi-node identity (§3.9) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,   -- ESP32 MAC address
    label       TEXT,               -- optional human-friendly name
    first_seen  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE telemetry ADD COLUMN IF NOT EXISTS node_id TEXT REFERENCES nodes(id);
ALTER TABLE sessions  ADD COLUMN IF NOT EXISTS node_id TEXT REFERENCES nodes(id);

-- ── 2. Session model redesign (§3.3) ────────────────────────────────────
-- Drop the FK-gating column. This is the change that lets publishers write
-- telemetry with zero knowledge of sessions.
ALTER TABLE telemetry DROP COLUMN IF EXISTS session_id;

-- sessions.ended_at already exists and is already nullable — no DDL change
-- needed there. NULL = open, treated as NOW() by every consumer at query
-- time (not enforced by the schema itself, just the agreed convention).

-- Optional: a user-facing name field, since the frontend now lets users
-- create/name sessions directly (architecture.md §2.5, §3.3). Kept
-- separate from `notes`.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS name TEXT;

-- Index to support the new range-join query pattern
-- (sessions(started_at, ended_at) — equality lookups no longer apply).
CREATE INDEX IF NOT EXISTS idx_sessions_time_range
    ON sessions (started_at, ended_at);

-- ── 4. Recreate telemetry_1min without session_id ───────────────────────
-- Same aggregate columns as before, minus the session_id grouping key.
-- KNOWN GAP (documented, not this chat's job to fix): Grafana's panel
-- queries/template variables still filter on the old `session_id =`
-- equality pattern and will need the same time-range-join fix applied
-- here — see architecture.md §3.7 and this chat's stated exclusions.
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1min
WITH (timescaledb.continuous) AS
    SELECT
        time_bucket('1 minute', time) AS bucket,
        AVG(speed_kmh)          AS avg_speed,
        MAX(speed_kmh)          AS max_speed,
        AVG(rpm)                AS avg_rpm,
        AVG(throttle_pct)       AS avg_throttle,
        AVG(engine_load_pct)    AS avg_load,
        MAX(ABS(accel_x))       AS max_accel_x,
        MAX(ABS(accel_y))       AS max_accel_y
    FROM telemetry
    GROUP BY bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy('telemetry_1min',
    start_offset => INTERVAL '1 hour',
    end_offset => NULL,
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

COMMIT;

-- Recreated WITH NO DATA (same as the original), so — same rule as
-- always — it needs a one-time manual backfill against your existing
-- 50k+ mock rows. Run this AFTER the COMMIT above, not inside the same
-- transaction (continuous aggregate refreshes can't run inside an
-- explicit transaction block):
--
--   CALL refresh_continuous_aggregate('telemetry_1min', NULL, NULL);
--
-- Skipping this will make it look like the migration silently deleted
-- all your historical Grafana data — it didn't, it's just an empty
-- aggregate until this call runs.

-- ── 3. Verification query — RUN THIS AGAINST THE LIVE DB AND PASTE BACK ─
-- Sanity-checks the claim in the chat brief that a prior session already
-- backfilled sessions.started_at/ended_at from telemetry's real min/max
-- timestamps. This checks whether every existing telemetry row actually
-- falls inside some session's time window under the new join pattern.
--
-- Expected if backfill is consistent: orphan_count = 0.
-- If orphan_count > 0, some telemetry rows predate/postdate every
-- session's window and won't show up in any session-scoped query until
-- sessions' windows are widened or a new backfill session covers them.

SELECT COUNT(*) AS orphan_count
FROM telemetry t
WHERE NOT EXISTS (
    SELECT 1 FROM sessions s
    WHERE t.time BETWEEN s.started_at AND COALESCE(s.ended_at, NOW())
);

-- Also useful to see the actual windows vs. data extent:
SELECT
    s.id, s.name, s.started_at, s.ended_at,
    (SELECT MIN(time) FROM telemetry) AS data_min_time,
    (SELECT MAX(time) FROM telemetry) AS data_max_time
FROM sessions s
ORDER BY s.started_at;