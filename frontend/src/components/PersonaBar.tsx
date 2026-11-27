"use client";

import { Columns2, ShieldCheck } from "lucide-react";

import type { Persona } from "@/lib/types";
import { ClearanceBadge } from "./ClearanceBadge";

interface PersonaBarProps {
  personas: Persona[];
  activePersona: Persona | null;
  compareMode: boolean;
  switching: boolean;
  onSelectPersona: (persona: Persona) => void;
  onToggleCompare: () => void;
}

export function PersonaBar({
  personas,
  activePersona,
  compareMode,
  switching,
  onSelectPersona,
  onToggleCompare,
}: PersonaBarProps) {
  return (
    <header className="border-b border-slate-800/80 bg-[#0b111e]/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-white">EnclaveRAG</h1>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                PostgreSQL FORCE RLS
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Zero-Trust Multi-Tenant RAG · Database-Enforced Clearance Control
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {personas.map((persona) => {
            const isActive = activePersona?.email === persona.email && !compareMode;
            return (
              <button
                key={persona.user_id}
                type="button"
                disabled={switching}
                onClick={() => onSelectPersona(persona)}
                className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-xs transition ${
                  isActive
                    ? "border-sky-400/70 bg-sky-500/15 text-white shadow-sm shadow-sky-500/10"
                    : "border-slate-800 bg-slate-900/70 text-slate-300 hover:border-slate-700 hover:bg-slate-800/80"
                }`}
              >
                <div className="leading-tight">
                  <div className="font-semibold">{persona.org_name}</div>
                  <div className="text-[11px] text-slate-400">{persona.role_title}</div>
                </div>
                <ClearanceBadge level={persona.clearance_level} />
              </button>
            );
          })}

          <button
            type="button"
            onClick={onToggleCompare}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
              compareMode
                ? "border-violet-400/70 bg-violet-500/20 text-violet-200"
                : "border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-600 hover:text-white"
            }`}
          >
            <Columns2 className="h-3.5 w-3.5" />
            Compare L1 vs L4
          </button>
        </div>
      </div>
    </header>
  );
}
