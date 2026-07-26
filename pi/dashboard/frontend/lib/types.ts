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

export type WsMessage =
  | { type: "telemetry"; data: TelemetryData }
  | { type: "advanced_pids"; ts: number; data: AdvancedPidsData }
  | { type: "active_sessions"; data: Session[] };

export type ConnectionStatus = "connecting" | "open" | "closed" | "reconnecting";