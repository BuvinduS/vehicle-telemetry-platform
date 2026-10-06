"use client";

import { useEffect, useState } from "react";
import { useTelemetryContext } from "@/lib/telemetry-context";
import { useViewMode } from "@/lib/view-mode";
import { listSessions } from "@/lib/sessionsAPI";
import { useSessionSummary } from "@/lib/useSessionSummary";
import type { Session, SessionSummary } from "@/lib/types";

const MONO = "var(--font-geist-mono)";

function fmt(v: number | null | undefined, digits = 0): string {
  return v == null ? "--" : v.toFixed(digits);
}

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return "--";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(sec).padStart(2, "0")}s`;
}

function sessionLabel(s: Session): string {
  const when = new Date(s.started_at).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  return `${s.name || "Untitled session"} · ${when}${s.ended_at ? "" : " · live"}`;
}

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  const missing = value === "--";
  return (
    <div className="flex flex-col gap-1 rounded-sm px-4 py-3" style={{ backgroundColor: "var(--color-panel-raised)" }}>
      <span className="text-xs font-semibold uppercase tracking-widest text-ink-dim">{label}</span>
      <span
        className="text-2xl tabular-nums"
        style={{ fontFamily: MONO, color: missing ? "var(--color-ink-faint)" : "var(--color-accent)" }}
      >
        {value}
        {unit && !missing && <span className="text-sm text-ink-dim ml-1">{unit}</span>}
      </span>
    </div>
  );
}

function SpeedSparkline({ trace }: { trace: SessionSummary["speed_trace"] }) {
  if (trace.length < 2) return null;
  const W = 600;
  const H = 80;
  const maxV = Math.max(...trace.map((p) => p.v), 1);
  const points = trace
    .map((p, i) => `${(i / (trace.length - 1)) * W},${H - (p.v / maxV) * (H - 4) - 2}`)
    .join(" ");
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-semibold uppercase tracking-widest text-ink-dim">Speed over time</span>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-20">
        <polyline
          points={points}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

export default function SessionSummaryOverlay() {
  const { setViewMode } = useViewMode();
  const { activeSessions } = useTelemetryContext();

  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  // Refetch the picker list on mount and whenever the set of open sessions
  // changes (one started or ended anywhere) so ended_at stays current.
  const openKey = activeSessions.map((s) => s.id).join(",");
  useEffect(() => {
    let cancelled = false;
    listSessions()
      .then((rows) => {
        if (!cancelled) {
          setSessions(rows);
          setListError(null);
        }
      })
      .catch(() => {
        if (!cancelled) setListError("Couldn't load sessions.");
      });
    return () => {
      cancelled = true;
    };
  }, [openKey]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewMode("normal");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setViewMode]);

  // Until the user picks one, default to the newest session.
  const session = sessions.find((s) => s.id === selectedId) ?? sessions[0] ?? null;
  const { summary, loading, error } = useSessionSummary(session);
  const shownError = listError ?? error;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0"
        onClick={() => setViewMode("normal")}
        style={{
          backgroundColor: "var(--color-bg)",
          opacity: 0.85,
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
        }}
      />

      <div
        className="relative flex flex-col gap-5 rounded-sm p-6 w-full max-w-5xl max-h-[90vh] overflow-y-auto"
        style={{ backgroundColor: "var(--color-panel)", border: "1px solid var(--color-hairline)" }}
      >
        <div className="flex items-center justify-between gap-4">
          <span className="text-xs font-semibold uppercase tracking-widest text-ink-dim">Drive Summary</span>
          <div className="flex items-center gap-3">
            <select
              value={session?.id ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
              disabled={sessions.length === 0}
              className="text-sm px-3 py-2 rounded-sm"
              style={{ backgroundColor: "var(--color-bg)", border: "1px solid var(--color-hairline)", color: "var(--color-ink)" }}
            >
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {sessionLabel(s)}
                </option>
              ))}
            </select>
            <button
              onClick={() => setViewMode("normal")}
              className="text-xs font-semibold uppercase tracking-widest px-3 py-2 rounded-sm"
              style={{ color: "var(--color-ink-dim)", border: "1px solid var(--color-hairline)" }}
            >
              Close ✕
            </button>
          </div>
        </div>

        {shownError && (
          <p className="text-xs" style={{ color: "var(--color-danger)" }}>
            {shownError}
          </p>
        )}

        {!session ? (
          <div className="py-16 text-center text-sm text-ink-faint">
            No sessions yet — start one from the Sessions panel.
          </div>
        ) : !summary ? (
          <div className="py-16 text-center text-sm text-ink-faint">
            {loading || !shownError ? "Loading…" : "Summary unavailable."}
          </div>
        ) : summary.row_count === 0 ? (
          <div className="py-16 text-center text-sm text-ink-faint">
            No telemetry recorded in this session&apos;s window yet.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label="Distance" value={fmt(summary.distance_km, 1)} unit="km" />
              <Stat label="Duration" value={fmtDuration(summary.duration_s)} />
              <Stat label="Avg speed" value={fmt(summary.avg_speed_kmh, 0)} unit="km/h" />
              <Stat label="Max speed" value={fmt(summary.max_speed_kmh, 0)} unit="km/h" />

              <Stat label="Max RPM" value={fmt(summary.max_rpm, 0)} unit="rpm" />
              <Stat label="Avg engine load" value={fmt(summary.avg_engine_load_pct, 0)} unit="%" />
              <Stat label="Peak coolant" value={fmt(summary.max_coolant_temp_c, 0)} unit="°C" />
              <Stat label="Time idle" value={fmt(summary.idle_pct, 0)} unit="%" />

              <Stat label="Peak G" value={fmt(summary.peak_g, 2)} unit="g" />
              <Stat label="Hard braking" value={fmt(summary.harsh_brake_count, 0)} />
              <Stat label="Hard accel" value={fmt(summary.harsh_accel_count, 0)} />
              <Stat label="Best 0–60" value={fmt(summary.best_0_60_s, 1)} unit="s" />
            </div>

            <SpeedSparkline trace={summary.speed_trace} />

            <p className="text-xs text-ink-faint">
              Hard braking / accel: longitudinal acceleration beyond 0.3 g, counted once per event.
              Best 0–60: fastest standstill-to-60 km/h run in the session.
              {session.ended_at === null && " Live session: updating every few seconds."}
            </p>
          </>
        )}
      </div>
    </div>
  );
}