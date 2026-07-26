interface ThermometerProps {
  label: string;
  value: number | null;
  min: number;
  max: number;
  unit: string;
  digits?: number;
  /** value at/above which this reads as "elevated" (accent color) */
  warnAt?: number;
  /** value at/above which this reads as "critical" (danger color) — takes priority over warnAt */
  dangerAt?: number;
  width?: number;
  height?: number;
}

export default function Thermometer({
  label,
  value,
  min,
  max,
  unit,
  digits = 0,
  warnAt,
  dangerAt,
  width = 140,
  height = 10,
}: ThermometerProps) {
  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
  const displayValue = hasValue ? value : min;
  const frac = Math.min(1, Math.max(0, (displayValue - min) / (max - min)));

  const isDanger = dangerAt !== undefined && hasValue && (value as number) >= dangerAt;
  const isWarn = !isDanger && warnAt !== undefined && hasValue && (value as number) >= warnAt;

  const fillColor = !hasValue
    ? "var(--color-ink-faint)"
    : isDanger
    ? "var(--color-danger)"
    : isWarn
    ? "var(--color-accent)"
    : "var(--color-accent-secondary)";

  return (
    <div className="flex items-center gap-3 whitespace-nowrap">
      <span className="text-xl font-semibold uppercase tracking-widest text-ink-dim">
        {label}:
      </span>

      <div
        className="relative rounded-sm overflow-hidden"
        style={{ width, height, backgroundColor: "var(--color-panel)", border: "1px solid var(--color-hairline)" }}
      >
        {warnAt !== undefined && (
          <div
            className="absolute top-0 bottom-0 w-px"
            style={{ left: `${((warnAt - min) / (max - min)) * 100}%`, backgroundColor: "var(--color-accent)", opacity: 0.5 }}
          />
        )}
        {dangerAt !== undefined && (
          <div
            className="absolute top-0 bottom-0 w-px"
            style={{ left: `${((dangerAt - min) / (max - min)) * 100}%`, backgroundColor: "var(--color-danger)", opacity: 0.6 }}
          />
        )}
        <div
          className="absolute top-0 bottom-0 left-0 transition-[width] duration-300"
          style={{ width: `${frac * 100}%`, backgroundColor: fillColor, opacity: hasValue ? 1 : 0.3 }}
        />
      </div>

      <span className="flex items-baseline gap-1 transition-colors duration-200" style={{ color: fillColor }}>
        <span className="text-3xl font-semibold tabular-nums" style={{ fontFamily: "var(--font-geist-mono)" }}>
          {hasValue ? (value as number).toFixed(digits) : "--"}
        </span>
        <span className="text-md" style={{ color: "var(--color-ink-faint)" }}>
          {unit}
        </span>
      </span>
    </div>
  );
}