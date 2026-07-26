"use client";

import { useViewMode } from "@/lib/view-mode";

export default function ViewToggle() {
  const { viewMode, setViewMode } = useViewMode();

  return (
    <div className="flex rounded-sm overflow-hidden" style={{ border: "1px solid var(--color-hairline)" }}>
      {(["normal", "advanced"] as const).map((v) => (
        <button
          key={v}
          onClick={() => setViewMode(v)}
          className="px-3 py-1.5 text-xs font-semibold uppercase tracking-widest transition-colors"
          style={{
            backgroundColor: viewMode === v ? "var(--color-accent)" : "transparent",
            color: viewMode === v ? "var(--color-accent-ink)" : "var(--color-ink-dim)",
          }}
        >
          {v}
        </button>
      ))}
    </div>
  );
}