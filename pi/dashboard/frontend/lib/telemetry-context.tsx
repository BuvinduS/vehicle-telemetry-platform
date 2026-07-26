"use client";

import { createContext, useContext } from "react";
import { useTelemetry } from "./useTelemetry";

type TelemetryContextValue = ReturnType<typeof useTelemetry>;

const TelemetryContext = createContext<TelemetryContextValue | null>(null);

export function TelemetryProvider({ children }: { children: React.ReactNode }) {
  const telemetry = useTelemetry();
  return <TelemetryContext.Provider value={telemetry}>{children}</TelemetryContext.Provider>;
}

export function useTelemetryContext() {
  const ctx = useContext(TelemetryContext);
  if (!ctx) throw new Error("useTelemetryContext must be used within a TelemetryProvider");
  return ctx;
}