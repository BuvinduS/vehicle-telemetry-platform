// app/components/ModeSwitcher.tsx
"use client";

import { useMode, MODES } from "@/lib/mode";

export default function ModeSwitcher() {
  const { mode, setMode } = useMode();

  return (
    <div className="flex gap-2">
      {MODES.map((m) => (
        <button
          key={m.id}
          onClick={() => setMode(m.id)}
          className={`px-4 py-2 rounded font-semibold ${
            mode === m.id ? "bg-accent text-accent-ink" : "bg-panel text-ink-dim"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}