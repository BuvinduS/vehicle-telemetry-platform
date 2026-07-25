// Shared polar/arc math for every SVG-based instrument (ArcGauge now;
// Thermometer/GForcePanel will reuse pieces of this later).

/** Maps a value in [min, max] to an angle along a gauge's sweep. */
export function valueToAngle(
  value: number,
  min: number,
  max: number,
  startDeg: number,
  sweepDeg: number
): number {
  const clamped = Math.min(max, Math.max(min, value));
  const frac = (clamped - min) / (max - min);
  return startDeg + frac * sweepDeg;
}

/** Converts a polar coordinate (center + radius + angle) to an {x, y} point.
 *  0° points "up" (12 o'clock), matching how a real gauge face reads. */
export function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/** Builds an SVG arc path between two angles, for a given center/radius. */
export function arcPath(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polar(cx, cy, r, endAngle);
  const end = polar(cx, cy, r, startAngle);
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
}