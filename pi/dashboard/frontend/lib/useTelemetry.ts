"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { wsUrl } from "./config";
import type { TelemetryData, AdvancedPidsData, Session, ConnectionStatus, WsMessage, VehicleInfo } from "./types";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;

export function useTelemetry() {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const [advancedPids, setAdvancedPids] = useState<AdvancedPidsData | null>(null);
  const [advancedPidsTs, setAdvancedPidsTs] = useState<number | null>(null);
  const [activeSessions, setActiveSessions] = useState<Session[]>([]);

  const lastTelemetryAt = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUs = useRef(false);

  const messageTimes = useRef<number[]>([]);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [avgIntervalMs, setAvgIntervalMs] = useState<number | null>(null);

  const [vehicleInfo, setVehicleInfo] = useState<VehicleInfo | null>(null);


  const lastTelemetryAgeMs = useCallback(() => {
    if (lastTelemetryAt.current === null) return null;
    return Date.now() - lastTelemetryAt.current;
  }, []);

  useEffect(() => {
    closedByUs.current = false;

    function connect() {
      setStatus(reconnectAttempt.current === 0 ? "connecting" : "reconnecting");
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt.current = 0;
        setStatus("open");
      };

      ws.onmessage = (event) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (msg.type) {
          case "telemetry": {
            setTelemetry(msg.data);
            const now = Date.now();
            lastTelemetryAt.current = now;
            setLatencyMs(now - msg.data.ts * 1000);

            const times = messageTimes.current;
            times.push(now);
            if (times.length > 20) times.shift();
            if (times.length >= 2) {
                const deltas = times.slice(1).map((t, i) => t - times[i]);
                setAvgIntervalMs(deltas.reduce((a, b) => a + b, 0) / deltas.length);
            }
            break;
        }
          case "advanced_pids":
            setAdvancedPids(msg.data);
            setAdvancedPidsTs(msg.ts);
            break;
          case "active_sessions":
            setActiveSessions(msg.data);
            break;
          case "vehicle_info":
            setVehicleInfo(msg.data);
            break;
        }
      };

      ws.onclose = () => {
        setStatus("closed");
        if (closedByUs.current) return;
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt.current, RECONNECT_MAX_MS);
        reconnectAttempt.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      closedByUs.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, []);

  return { status, telemetry, advancedPids, advancedPidsTs, activeSessions, vehicleInfo, latencyMs, avgIntervalMs, lastTelemetryAgeMs };
}