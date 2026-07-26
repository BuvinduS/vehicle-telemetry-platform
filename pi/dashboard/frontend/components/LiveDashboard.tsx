"use client";

import ArcGauge from "@/components/ArcGauge";
import NumericReadout from "@/components/NumericReadout";
import Thermometer from "@/components/Thermometer";
import GForcePanel from "@/components/GForcePanel";
import SessionPanel from "@/components/SessionPanel";
import CollapsiblePanel from "@/components/CollapsiblePanel";
import { useTelemetryContext } from "@/lib/telemetry-context";

export default function LiveDashboard() {
  const { telemetry, latencyMs, avgIntervalMs } = useTelemetryContext();
  const t = telemetry;

  return (
    <>
      <div className="flex items-start gap-6 flex-1">
        <div className="flex flex-col gap-4 pl-4">
          <div className="flex flex-col gap-4">
            <NumericReadout label="Throttle" value={t?.throttle_pct ?? null} unit="%" warnAt={85} />
            <NumericReadout label="Engine Load" value={t?.engine_load_pct ?? null} unit="%" warnAt={70} dangerAt={90} />
            <Thermometer label="Coolant" value={t?.coolant_temp_c ?? null} min={0} max={130} unit="°C" warnAt={100} dangerAt={115} />
          </div>
          <div className="mt-8">
            <GForcePanel accelX={t?.accel_x ?? null} accelY={t?.accel_y ?? null} />
          </div>
        </div>

        <div className="flex-1 flex items-center justify-center gap-12 mt-60">
          <ArcGauge label="Speed" value={t?.speed_kmh ?? null} min={0} max={220} unit="km/h" size={460} />
          <ArcGauge label="Engine" value={t?.rpm ?? null} min={0} max={7000} redline={6000} unit="rpm" size={460} />
        </div>

        <div className="pr-4">
          <CollapsiblePanel label="Sessions">
            <SessionPanel />
          </CollapsiblePanel>
        </div>
      </div>

      {process.env.NODE_ENV !== "production" && (
        <div className="fixed bottom-2 right-2 text-xs font-mono text-ink-dim bg-panel border border-hairline rounded px-2 py-1">
          latency: {latencyMs != null ? `${latencyMs.toFixed(0)}ms` : "--"} · interval:{" "}
          {avgIntervalMs != null ? `${avgIntervalMs.toFixed(0)}ms` : "--"}
        </div>
      )}
    </>
  );
}