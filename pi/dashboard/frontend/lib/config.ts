const DEFAULT_PORT = "8000";

function resolveHost(): string {
  const override = process.env.NEXT_PUBLIC_API_HOST;
  if (override) return override;
  if (typeof window !== "undefined") return `${window.location.hostname}:${DEFAULT_PORT}`;
  return `localhost:${DEFAULT_PORT}`;
}

export function apiBaseUrl(): string {
  const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "https" : "http";
  return `${protocol}://${resolveHost()}`;
}

export function wsUrl(): string {
  const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${resolveHost()}/ws/telemetry`;
}