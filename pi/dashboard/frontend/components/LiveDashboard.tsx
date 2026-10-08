"use client";

import ArcGauge from "@/components/ArcGauge";
import NumericReadout from "@/components/NumericReadout";
import Thermometer from "@/components/Thermometer";
import GForcePanel from "@/components/GForcePanel";
import SessionPanel from "@/components/SessionPanel";
import CollapsiblePanel from "@/components/CollapsiblePanel";
import { useTelemetryContext } from "@/lib/telemetry-context";
import { useViewMode } from "@/lib/view-mode";
import SessionSummaryOverlay from "@/components/SessionSummaryOverlay";

export default function LiveDashboard() {
  const { telemetry, latencyMs, avgIntervalMs } = useTelemetryContext();
  const { viewMode } = useViewMode();
  const t = telemetry;

  return (
    <>
      <div className="flex flex-col xl:flex-row xl:items-start gap-6 flex-1">
        <div className="flex flex-col gap-4 xl:pl-4">
          <div className="flex flex-col gap-4">
            <NumericReadout label="Throttle" value={t?.throttle_pct ?? null} unit="%" warnAt={85} />
            <NumericReadout label="Engine Load" value={t?.engine_load_pct ?? null} unit="%" warnAt={70} dangerAt={90} />
            <Thermometer label="Coolant" value={t?.coolant_temp_c ?? null} min={0} max={130} unit="°C" warnAt={100} dangerAt={115} />
          </div>
          <div className="mt-8">
            <GForcePanel accelX={t?.accel_x ?? null} accelY={t?.accel_y ?? null} />
          </div>
        </div>

        <div className="order-first xl:order-none xl:flex-1 flex flex-col xl:flex-row items-center justify-center gap-6 xl:gap-12 mt-4 xl:mt-60">
          <div className="w-full max-w-[min(100%,max(12rem,calc((100svh_-_14rem)/1.64)))] xl:contents">
            <ArcGauge label="Speed" value={t?.speed_kmh ?? null} min={0} max={220} unit="km/h" size={460} />
          </div>
          <div className="w-full max-w-[min(100%,max(12rem,calc((100svh_-_14rem)/1.64)))] xl:contents">
            <ArcGauge label="Engine" value={t?.rpm ?? null} min={0} max={7000} redline={6000} unit="rpm" size={460} />
          </div>
        </div>

        <div className="xl:pr-4">
          <CollapsiblePanel label="Sessions">
            <SessionPanel />
          </CollapsiblePanel>
        </div>
      </div>

      {viewMode === "advanced" && <SessionSummaryOverlay />}

      {process.env.NODE_ENV !== "production" && (
        <div className="fixed bottom-2 right-2 text-xs font-mono text-ink-dim bg-panel border border-hairline rounded px-2 py-1">
          latency: {latencyMs != null ? `${latencyMs.toFixed(0)}ms` : "--"} · interval:{" "}
          {avgIntervalMs != null ? `${avgIntervalMs.toFixed(0)}ms` : "--"}
        </div>
      )}
    </>
  );
}