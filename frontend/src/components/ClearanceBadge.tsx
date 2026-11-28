"use client";

import { CLEARANCE_LABELS } from "@/lib/types";
import { formatTierLabel, useAppStore } from "@/store/useAppStore";

export function ClearanceBadge({ level }: { level: number }) {
  const clearanceLabels = useAppStore((s) => s.clearanceLabels);
  const meta = CLEARANCE_LABELS[level] ?? {
    tag: `L${level}`,
    style: "bg-slate-700/40 text-slate-300 border-slate-600",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide ${meta.style}`}
    >
      {formatTierLabel(level, clearanceLabels)}
    </span>
  );
}
