"use client";

import { useEffect, useRef, useState } from "react";

interface GForcePanelProps {
  accelX: number | null; // lateral (cornering), m/s²
  accelY: number | null; // longitudinal (braking/accelerating), m/s²
  maxG?: number;
  trailLength?: number;
  size?: number;
}

const G = 9.81;

export default function GForcePanel({
  accelX,
  accelY,
  maxG = 1.2,
  trailLength = 20,
  size = 320,
}: GForcePanelProps) {
  const [trail, setTrail] = useState<{ x: number; y: number }[]>([]);
  const lastAdded = useRef(0);

  const hasValue =
    accelX !== null && accelY !== null && !Number.isNaN(accelX) && !Number.isNaN(accelY);

  useEffect(() => {
    if (!hasValue) return;
    const now = Date.now();
    if (now - lastAdded.current < 80) return; // throttle trail resolution
    lastAdded.current = now;
    setTrail((prev) => [...prev, { x: (accelX as number) / G, y: (accelY as number) / G }].slice(-trailLength));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accelX, accelY]);

  const c = size / 2;
  const scale = (c - 14) / maxG;
  const toXY = (gx: number, gy: number) => ({ x: c + gx * scale, y: c - gy * scale });
  const current = hasValue ? toXY((accelX as number) / G, (accelY as number) / G) : null;
  const rings = [0.25, 0.5, 0.75, 1.0].map((f) => f * maxG);

  return (
    <div
        className="flex flex-col items-center gap-2 rounded-sm p-4"
        style={{ backgroundColor: "var(--color-panel)", border: "1px solid var(--color-hairline)" }}
    >
        <div className="text-xl font-semibold uppercase tracking-widest text-ink-dim">G-Force</div>
    <svg width={size*1.2} height={size} viewBox={`0 0 ${size} ${size}`}>
        {rings.map((g) => (
          <circle key={g} cx={c} cy={c} r={g * scale} fill="none" stroke="var(--color-hairline)" strokeWidth={1} />
        ))}
        <line x1={12} y1={c} x2={size - 12} y2={c} stroke="var(--color-hairline)" strokeWidth={1} />
        <line x1={c} y1={12} x2={c} y2={size - 12} stroke="var(--color-hairline)" strokeWidth={1} />

        {trail.map((p, i) => {
          const xy = toXY(p.x, p.y);
          const age = i / trail.length;
          return (
            <circle key={i} cx={xy.x} cy={xy.y} r={2} fill="var(--color-accent-secondary)" opacity={0.15 + age * 0.35} />
          );
        })}

        {current && (
          <>
            <circle cx={current.x} cy={current.y} r={6} fill="none" stroke="var(--color-accent)" strokeWidth={2} />
            <circle cx={current.x} cy={current.y} r={2.5} fill="var(--color-accent)" />
          </>
        )}
    </svg>
      <div className="flex gap-3 text-xs tabular-nums" style={{ color: "var(--color-ink-dim)", fontFamily: "var(--font-geist-mono)" }}>
        <span>LAT {hasValue ? ((accelX as number) / G).toFixed(2) : "--"}g</span>
        <span>LON {hasValue ? ((accelY as number) / G).toFixed(2) : "--"}g</span>
      </div>
    </div>
  );
}