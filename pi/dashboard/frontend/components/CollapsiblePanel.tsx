"use client";

import { useState } from "react";

interface CollapsiblePanelProps {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export default function CollapsiblePanel({ label, defaultOpen = true, children }: CollapsiblePanelProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs font-semibold uppercase tracking-widest px-3 py-1.5 rounded-sm"
        style={{ color: "var(--color-ink-dim)", border: "1px solid var(--color-hairline)", backgroundColor: "var(--color-panel)" }}
      >
        {label} {open ? "▾" : "▸"}
      </button>
      {open && <div className="w-64">{children}</div>}
    </div>
  );
}