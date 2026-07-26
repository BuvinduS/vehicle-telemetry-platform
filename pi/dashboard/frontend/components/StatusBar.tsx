"use client";

import { useEffect, useState } from "react";
import ModeSwitcher from "./ModeSwitcher";
import { useTelemetryContext } from "@/lib/telemetry-context";

const STATUS_COPY: Record<string, { label: string; color: string; pulse: boolean }> = {
  connecting: { label: "CONNECTING", color: "var(--color-ink-dim)", pulse: true },
  open: { label: "LIVE", color: "var(--color-good)", pulse: true },
  reconnecting: { label: "RECONNECTING", color: "var(--color-accent)", pulse: true },
  closed: { label: "NO CONNECTION", color: "var(--color-danger)", pulse: false },
};

export default function StatusBar() {
  const { status } = useTelemetryContext();
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString(undefined, { hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const s = STATUS_COPY[status];

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full"
          style={{
            backgroundColor: s.color,
            boxShadow: `0 0 6px 1px ${s.color}`,
            animation: s.pulse ? "pulse-status 1.6s ease-in-out infinite" : "none",
          }}
        />
        <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: s.color }}>
          {s.label}
        </span>
      </div>

      <div className="flex items-center gap-6">
        <span className="text-sm tabular-nums text-ink-dim" style={{ fontFamily: "var(--font-geist-mono)" }}>
          {clock}
        </span>
        <ModeSwitcher />
      </div>
    </div>
  );
}