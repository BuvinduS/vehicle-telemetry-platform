import { valueToAngle, polar, arcPath } from "@/lib/gauge-math";

interface ArcGaugeProps {
  label: string;
  value: number | null;
  min: number;
  max: number;
  unit: string;
  redline?: number;
  digits?: number;
  /** max-width cap in px — the gauge fills its container up to this size */
  size?: number;
}

const SWEEP_DEG = 220;
const START_DEG = -110;
const TICK_COUNT = 10;
const V = 240; // internal coordinate system — arbitrary, decoupled from visual size

export default function ArcGauge({
  label,
  value,
  min,
  max,
  unit,
  redline,
  digits = 0,
  size = 420,
}: ArcGaugeProps) {
  const cx = V / 2;
  const cy = V / 2;
  const r = V * 0.38;

  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
  const displayValue = hasValue ? value : min;
  const isHot = redline !== undefined && hasValue && (value as number) >= redline;

  const needleAngle = valueToAngle(displayValue, min, max, START_DEG, SWEEP_DEG);
  const redlineAngle =
    redline !== undefined ? valueToAngle(redline, min, max, START_DEG, SWEEP_DEG) : null;

  const ticks = Array.from({ length: TICK_COUNT + 1 }, (_, i) => {
    const angle = START_DEG + (i / TICK_COUNT) * SWEEP_DEG;
    const tickValue = min + (i / TICK_COUNT) * (max - min);
    return {
      key: i,
      outer: polar(cx, cy, r, angle),
      inner: polar(cx, cy, r - 10, angle),
      hot: redline !== undefined && tickValue >= redline,
    };
  });

  const needleColor = isHot ? "var(--color-danger)" : "var(--color-accent)";
  const needleTip = polar(cx, cy, r - 4, needleAngle);

  return (
    <div
      className="w-full flex flex-col items-center gap-1"
      style={{ maxWidth: size }}
      role="img"
      aria-label={`${label}: ${hasValue ? displayValue.toFixed(digits) : "no data"} ${unit}`}
    >
      <div className="text-xs font-semibold uppercase tracking-widest text-ink-dim">{label}</div>

      <svg
        viewBox={`0 0 ${V} ${V}`}
        width="100%"
        style={{ aspectRatio: "1 / 0.82" }}
      >
        <path d={arcPath(cx, cy, r, START_DEG, START_DEG + SWEEP_DEG)} fill="none" stroke="var(--color-hairline)" strokeWidth={3} strokeLinecap="round" />

        {redlineAngle !== null && (
          <path d={arcPath(cx, cy, r, redlineAngle, START_DEG + SWEEP_DEG)} fill="none" stroke="var(--color-danger)" strokeWidth={3} strokeLinecap="round" opacity={0.35} />
        )}

        <path d={arcPath(cx, cy, r, START_DEG, needleAngle)} fill="none" stroke={needleColor} strokeWidth={3} strokeLinecap="round" opacity={hasValue ? 1 : 0.25} />

        {ticks.map((t) => (
          <line key={t.key} x1={t.inner.x} y1={t.inner.y} x2={t.outer.x} y2={t.outer.y} stroke={t.hot ? "var(--color-danger)" : "var(--color-ink-faint)"} strokeWidth={1.5} />
        ))}

        <g opacity={hasValue ? 1 : 0.3}>
          <line x1={cx} y1={cy} x2={needleTip.x} y2={needleTip.y} stroke={needleColor} strokeWidth={2} strokeLinecap="round" />
          <circle cx={cx} cy={cy} r={4} fill={needleColor} />
        </g>

        <text x={cx} y={cy + r * 0.62} textAnchor="middle" fontFamily="var(--font-geist-mono)" fontSize={V * 0.15} fontWeight={600} fill={hasValue ? "var(--color-ink)" : "var(--color-ink-faint)"}>
          {hasValue ? displayValue.toFixed(digits) : "--"}
        </text>
        <text x={cx} y={cy + r * 0.62 + V * 0.075} textAnchor="middle" fontSize={V * 0.05} fill="var(--color-ink-faint)">
          {unit}
        </text>
      </svg>
    </div>
  );
}