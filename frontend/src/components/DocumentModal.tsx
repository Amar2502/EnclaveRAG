"use client";

import { X } from "lucide-react";

import type { DocumentDetail } from "@/lib/types";
import { ClearanceBadge } from "./ClearanceBadge";

export function DocumentModal({
  document,
  onClose,
}: {
  document: DocumentDetail | null;
  onClose: () => void;
}) {
  if (!document) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-700 bg-[#0d1424] p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-3 border-b border-slate-800 pb-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-bold text-white">{document.title}</h3>
              <ClearanceBadge level={document.clearance_level} />
            </div>
            <p className="mt-1 font-mono text-[11px] text-slate-400">
              {document.department} · ID: {document.id}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3">
          {document.chunks.map((chunk) => (
            <div
              key={chunk.chunk_id}
              className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-xs leading-relaxed text-slate-200"
            >
              <div className="mb-1 font-mono text-[10px] text-slate-500">
                Chunk #{chunk.chunk_index}
              </div>
              <p className="whitespace-pre-wrap">{chunk.content}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
