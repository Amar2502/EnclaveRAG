"use client";

import { Database, Gauge, Layers } from "lucide-react";

import type { QueryTrace } from "@/lib/types";
import { ClearanceBadge } from "./ClearanceBadge";

export function XRayPanel({ trace }: { trace: QueryTrace | null }) {
  if (!trace) {
    return (
      <div className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-6 text-center text-xs text-slate-400">
        Run a query to inspect PostgreSQL <code className="text-slate-300">SET LOCAL</code>{" "}
        session claims, HNSW + FTS candidate counts, RRF scores, and latency breakdown.
      </div>
    );
  }

  return (
    <div className="space-y-4 text-xs">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
        <div className="mb-2 flex items-center gap-2 font-semibold text-slate-200">
          <Database className="h-4 w-4 text-emerald-400" />
          PostgreSQL SET LOCAL Scope
        </div>
        <div className="grid grid-cols-1 gap-1.5 font-mono text-[11px] text-slate-300">
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">app.org_id</span>
            <span className="truncate">{trace.rls_context.org_id}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">app.clearance_level</span>
            <ClearanceBadge level={trace.rls_context.clearance_level} />
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">app.user_id</span>
            <span className="truncate">{trace.rls_context.user_id}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-slate-500">hnsw.iterative_scan</span>
            <span className="text-emerald-300">
              {trace.retrieval.iterative_scan_enabled ? "relaxed_order" : "disabled"}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricBox label="Embed" value={`${trace.timings_ms.embed} ms`} />
        <MetricBox label="RLS Search" value={`${trace.timings_ms.retrieval} ms`} />
        <MetricBox label="Groq LLM" value={`${trace.timings_ms.llm} ms`} />
        <MetricBox label="Total" value={`${trace.timings_ms.total} ms`} highlight />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2 font-semibold text-slate-200">
            <Layers className="h-4 w-4 text-sky-400" />
            Hybrid RRF Funnel
          </div>
          <div className="text-[11px] text-slate-400">
            Vec: {trace.retrieval.vector_candidates} · FTS: {trace.retrieval.fts_candidates} · Fused:{" "}
            <span className="font-semibold text-white">{trace.retrieval.fused_count}</span>
          </div>
        </div>

        {trace.retrieval.chunks.length === 0 ? (
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-slate-400">
            0 chunks cleared the RLS policy &amp; relevance gate.
          </div>
        ) : (
          <div className="space-y-2">
            {trace.retrieval.chunks.map((chunk) => (
              <div
                key={chunk.chunk_id}
                className="rounded-lg border border-slate-800 bg-slate-950/70 p-2.5"
              >
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-slate-200">{chunk.document_title}</span>
                  <ClearanceBadge level={chunk.clearance_level} />
                </div>
                <p className="mb-1.5 text-[11px] leading-relaxed text-slate-400">
                  {chunk.snippet}
                </p>
                <div className="flex flex-wrap gap-3 font-mono text-[10px] text-slate-400">
                  <span>RRF: {chunk.rrf_score.toFixed(4)}</span>
                  <span>
                    Vec: {chunk.vector_score !== null ? chunk.vector_score.toFixed(3) : "—"}
                  </span>
                  <span>FTS: {chunk.fts_score !== null ? chunk.fts_score.toFixed(3) : "—"}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricBox({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-2.5 ${
        highlight
          ? "border-sky-500/40 bg-sky-500/10"
          : "border-slate-800 bg-slate-900/60"
      }`}
    >
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-slate-400">
        <Gauge className="h-3 w-3" />
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold text-white">{value}</div>
    </div>
  );
}
