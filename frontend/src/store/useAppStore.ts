"use client";

import { create } from "zustand";

export type ThemeMode = "dark" | "light";

export const DEFAULT_CLEARANCE_LABELS: Record<string, string> = {
  "1": "Company-Wide",
  "2": "Internal",
  "3": "Dept Confidential",
  "4": "Executive Only",
};

interface AppStoreState {
  theme: ThemeMode;
  clearanceLabels: Record<string, string>;
  initTheme: () => void;
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
  setClearanceLabels: (labels?: Record<string, string> | null) => void;
}

function applyThemeClass(theme: ThemeMode) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(theme);
}

export const useAppStore = create<AppStoreState>((set, get) => ({
  theme: "dark",
  clearanceLabels: DEFAULT_CLEARANCE_LABELS,
  initTheme: () => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem("enclaverag_theme");
    const theme: ThemeMode = saved === "light" ? "light" : "dark";
    applyThemeClass(theme);
    set({ theme });
  },
  toggleTheme: () => {
    const next: ThemeMode = get().theme === "dark" ? "light" : "dark";
    if (typeof window !== "undefined") {
      window.localStorage.setItem("enclaverag_theme", next);
    }
    applyThemeClass(next);
    set({ theme: next });
  },
  setTheme: (theme) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("enclaverag_theme", theme);
    }
    applyThemeClass(theme);
    set({ theme });
  },
  setClearanceLabels: (labels) => {
    if (!labels) {
      set({ clearanceLabels: DEFAULT_CLEARANCE_LABELS });
      return;
    }
    set({
      clearanceLabels: {
        ...DEFAULT_CLEARANCE_LABELS,
        ...labels,
      },
    });
  },
}));

export function formatTierLabel(
  level: number,
  labels?: Record<string, string> | null,
): string {
  const custom = labels?.[String(level)] ?? DEFAULT_CLEARANCE_LABELS[String(level)];
  return custom ? `L${level} · ${custom}` : `L${level}`;
}
