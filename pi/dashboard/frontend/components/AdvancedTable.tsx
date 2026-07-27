"use client";

import { useTelemetryContext } from "@/lib/telemetry-context";

export default function AdvancedTable() {
  const { advancedPids, advancedPidsTs } = useTelemetryContext();
  const entries = advancedPids ? Object.entries(advancedPids) : [];

  return (
    <div
      className="flex flex-col gap-3 rounded-sm p-4 w-full max-w-2xl"
      style={{ backgroundColor: "var(--color-panel)", border: "1px solid var(--color-hairline)" }}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold uppercase tracking-widest text-ink-dim">
          All Supported PIDs
        </span>
        <span className="text-xs text-ink-faint" style={{ fontFamily: "var(--font-geist-mono)" }}>
          {advancedPidsTs ? new Date(advancedPidsTs * 1000).toLocaleTimeString(undefined, { hour12: false }) : "--:--:--"}
        </span>
      </div>

      {entries.length === 0 ? (
        <div className="py-10 text-center text-sm text-ink-faint">
          No advanced-mode sweep received yet — expected until a publisher
          assembles a full PID sweep (architecture.md §3.10).
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-widest text-ink-dim" style={{ borderBottom: "1px solid var(--color-hairline)" }}>
              <th className="text-left py-1.5 font-semibold">PID</th>
              <th className="text-right py-1.5 font-semibold">Value</th>
              <th className="text-left py-1.5 pl-3 font-semibold">Unit</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([key, entry]) => {
              const missing = entry.value === null;
              return (
                <tr key={key} style={{ borderBottom: "1px solid var(--color-hairline)" }}>
                  <td className="py-1.5" style={{ color: missing ? "var(--color-ink-faint)" : "var(--color-ink)" }}>
                    {entry.desc || key}
                  </td>
                  <td
                    className="py-1.5 text-right tabular-nums"
                    style={{ color: missing ? "var(--color-ink-faint)" : "var(--color-accent)", fontFamily: "var(--font-geist-mono)" }}
                  >
                    {missing ? "--" : entry.value}
                  </td>
                  <td className="py-1.5 pl-3" style={{ color: missing ? "var(--color-ink-faint)" : "var(--color-ink-dim)" }}>
                    {entry.unit ?? ""}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}