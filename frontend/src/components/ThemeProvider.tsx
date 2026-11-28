"use client";

import { useEffect, type ReactNode } from "react";

import { getSession } from "@/lib/session";
import { useAppStore } from "@/store/useAppStore";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const initTheme = useAppStore((s) => s.initTheme);
  const setClearanceLabels = useAppStore((s) => s.setClearanceLabels);

  useEffect(() => {
    initTheme();
    const session = getSession();
    if (session?.user?.clearance_labels) {
      setClearanceLabels(session.user.clearance_labels);
    }
  }, [initTheme, setClearanceLabels]);

  return <>{children}</>;
}
