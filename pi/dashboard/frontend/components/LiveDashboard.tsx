"use client";

import { useTelemetry } from "@/lib/useTelemetry";
import ArcGauge from "@/components/ArcGauge";
import NumericReadout from "@/components/NumericReadout";
import Thermometer from "@/components/Thermometer";
import GForcePanel from "@/components/GForcePanel";

export default function LiveDashboard() {
  const { telemetry, latencyMs, avgIntervalMs } = useTelemetry();
  const t = telemetry;

  return (
    <>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center flex-1">
        <div className="flex flex-col gap-4 justify-self-start self-start pl-4">
          <div className="flex flex-col gap-4">
            <NumericReadout label="Throttle" value={t?.throttle_pct ?? null} unit="%" warnAt={85} />
            <NumericReadout label="Engine Load" value={t?.engine_load_pct ?? null} unit="%" warnAt={70} dangerAt={90} />
            <Thermometer
              label="Coolant"
              value={t?.coolant_temp_c ?? null}
              min={0}
              max={130}
              unit="°C"
              warnAt={100}
              dangerAt={115}
            />
          </div>
          <div className="mt-8">
            <GForcePanel accelX={t?.accel_x ?? null} accelY={t?.accel_y ?? null} />
          </div>
        </div>

        <div className="flex items-center gap-12">
          <ArcGauge label="Speed" value={t?.speed_kmh ?? null} min={0} max={220} unit="km/h" size={380} />
          <ArcGauge label="Engine" value={t?.rpm ?? null} min={0} max={7000} redline={6000} unit="rpm" size={380} />
        </div>

        <div />
      </div>

      {process.env.NODE_ENV !== "production" && (
        <div className="fixed bottom-2 right-2 text-xs font-mono text-ink-dim bg-panel border border-hairline rounded px-2 py-1">
          latency: {latencyMs !== null ? `${latencyMs.toFixed(0)}ms` : "--"} · interval:{" "}
          {avgIntervalMs !== null ? `${avgIntervalMs.toFixed(0)}ms` : "--"}
        </div>
      )}
    </>
  );
}