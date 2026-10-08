export interface TelemetryData {
  ts: number; // Unix epoch seconds — NOT converted to local tz server-side
  speed_kmh: number | null;
  rpm: number | null;
  throttle_pct: number | null;
  coolant_temp_c: number | null;
  engine_load_pct: number | null;
  accel_x: number | null;
  accel_y: number | null;
  accel_z: number | null;
}

export interface AdvancedPidEntry {
  value: number | null;
  unit: string | null;
  desc: string | null;
}

export type AdvancedPidsData = Record<string, AdvancedPidEntry>;

export interface Session {
  id: string;
  name: string | null;
  driver_id: string | null;
  node_id: string | null;
  started_at: string;
  ended_at: string | null;
  notes: string | null;
}

export interface SpeedPoint {
  t: string; // ISO timestamp
  v: number; // km/h
}

// Mirrors the backend's SessionSummaryResponse. Every stat is null when
// the session has no usable data for it; row_count === 0 means the
// session exists but has no telemetry in its window yet.
export interface SessionSummary {
  session_id: string;
  row_count: number;
  duration_s: number | null;
  avg_speed_kmh: number | null;
  max_speed_kmh: number | null;
  avg_rpm: number | null;
  max_rpm: number | null;
  avg_throttle_pct: number | null;
  max_throttle_pct: number | null;
  avg_coolant_temp_c: number | null;
  max_coolant_temp_c: number | null;
  avg_engine_load_pct: number | null;
  max_abs_accel_x: number | null;
  max_abs_accel_y: number | null;
  distance_km: number | null;
  idle_pct: number | null;
  peak_g: number | null;
  harsh_accel_count: number | null;
  harsh_brake_count: number | null;
  best_0_60_s: number | null;
  speed_trace: SpeedPoint[];
}

export interface VehicleInfo {
  vin: string | null;
  make: string | null;
  model: string | null;
  year: string | null;
}


export type WsMessage =
  | { type: "telemetry"; data: TelemetryData }
  | { type: "advanced_pids"; ts: number; data: AdvancedPidsData }
  | { type: "active_sessions"; data: Session[] }
  | { type: "vehicle_info"; data: VehicleInfo };

export type ConnectionStatus = "connecting" | "open" | "closed" | "reconnecting";

