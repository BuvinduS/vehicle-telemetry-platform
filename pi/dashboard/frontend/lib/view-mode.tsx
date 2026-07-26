"use client";

import { createContext, useContext, useState } from "react";

export type ViewMode = "normal" | "advanced";

interface ViewModeContextValue {
  viewMode: ViewMode;
  setViewMode: (v: ViewMode) => void;
}

const ViewModeContext = createContext<ViewModeContextValue>({
  viewMode: "normal",
  setViewMode: () => {},
});

export function ViewModeProvider({ children }: { children: React.ReactNode }) {
  const [viewMode, setViewMode] = useState<ViewMode>("normal");
  return <ViewModeContext.Provider value={{ viewMode, setViewMode }}>{children}</ViewModeContext.Provider>;
}

export function useViewMode() {
  return useContext(ViewModeContext);
}