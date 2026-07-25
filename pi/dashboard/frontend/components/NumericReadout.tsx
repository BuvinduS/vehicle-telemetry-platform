interface NumericReadoutProps {
  label: string;
  value: number | null;
  unit: string;
  digits?: number;
  /** value at/above which this reads as "elevated" (accent color) */
  warnAt?: number;
  /** value at/above which this reads as "critical" (danger color) — takes priority over warnAt */
  dangerAt?: number;
}

export default function NumericReadout({
  label,
  value,
  unit,
  digits = 0,
  warnAt,
  dangerAt,
}: NumericReadoutProps) {
  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
  const isDanger = dangerAt !== undefined && hasValue && (value as number) >= dangerAt;
  const isWarn = !isDanger && warnAt !== undefined && hasValue && (value as number) >= warnAt;

  const valueColor = !hasValue
    ? "var(--color-ink-faint)"
    : isDanger
    ? "var(--color-danger)"
    : isWarn
    ? "var(--color-accent)"
    : "var(--color-ink)";

  return (
    <div className="flex items-baseline gap-2 whitespace-nowrap">
      <span className="text-xl font-semibold uppercase tracking-widest text-ink-dim">
        {label}: 
      </span>
      <span className="flex items-baseline gap-1 transition-colors duration-200" style={{ color: valueColor }}>
        <span
          className="text-3xl font-semibold tabular-nums"
          style={{ fontFamily: "var(--font-geist-mono)" }}
        >
          {hasValue ? (value as number).toFixed(digits) : "--"}
        </span>
        <span className="text-xl" style={{ color: "var(--color-ink-faint)" }}>
          {unit}
        </span>
      </span>
    </div>
  );
}