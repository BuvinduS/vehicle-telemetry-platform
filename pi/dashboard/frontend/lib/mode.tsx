"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";

export const MODES = [
  { id: "sport", label: "Sport" },
  { id: "eco", label: "Eco" },
  { id: "track", label: "Track" },
  { id: "comfort", label: "Comfort" },
] as const;

export type ModeId = (typeof MODES)[number]["id"];

const STORAGE_KEY = "vtp-dashboard-mode";
const DEFAULT_MODE: ModeId = "sport";

const ModeContext = createContext<{ mode: ModeId; setMode: (m: ModeId) => void }>({
  mode: DEFAULT_MODE,
  setMode: () => {},
});

export function ModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ModeId>(DEFAULT_MODE);

  useEffect(() => {
    const current = document.documentElement.dataset.mode as ModeId | undefined;
    if (current && MODES.some((m) => m.id === current)) setModeState(current);
  }, []);

  const setMode = useCallback((m: ModeId) => {
    setModeState(m);
    document.documentElement.dataset.mode = m;
    try {
      window.localStorage.setItem(STORAGE_KEY, m);
    } catch {}
  }, []);

  return <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>;
}

export function useMode() {
  return useContext(ModeContext);
}

// inlined into layout.tsx's <head> to avoid a flash of Sport mode on reload
export const NO_FLASH_SCRIPT = `
(function () {
  try {
    var m = localStorage.getItem('${STORAGE_KEY}');
    if (m) document.documentElement.setAttribute('data-mode', m);
  } catch (e) {}
})();
`;