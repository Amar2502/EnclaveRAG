"use client";

import { Download, Layers, X } from "lucide-react";
import { useState } from "react";

import { downloadDocument } from "@/lib/api";
import type { DocumentDetail } from "@/lib/types";
import { ClearanceBadge } from "./ClearanceBadge";
import { MarkdownAnswer } from "./MarkdownAnswer";

export function DocumentModal({
  document,
  token,
  onClose,
}: {
  document: DocumentDetail | null;
  token?: string;
  onClose: () => void;
}) {
  const [showSections, setShowSections] = useState(false);
  const [downloading, setDownloading] = useState(false);

  if (!document) {
    return null;
  }

  const stitchedText =
    document.full_text ?? document.chunks.map((c) => c.content).join("\n\n");

  async function handleDownload() {
    if (!token || !document) return;
    setDownloading(true);
    try {
      await downloadDocument(token, document.id, document.title);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-700 bg-[#0d1424] p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-3 border-b border-slate-800 pb-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-bold text-white">{document.title}</h3>
              <ClearanceBadge level={document.clearance_level} />
              {document.version && document.version > 1 && (
                <span className="rounded-md border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-sky-300">
                  v{document.version}
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {document.department}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {document.has_download && token && (
              <button
                type="button"
                disabled={downloading}
                onClick={() => void handleDownload()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-2.5 py-1.5 text-xs font-medium text-sky-200 hover:bg-sky-500/20 disabled:opacity-50"
              >
                <Download className="h-3.5 w-3.5" />
                {downloading ? "Downloading..." : "Download Original"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowSections((prev) => !prev)}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 hover:text-white"
              title="Toggle between stitched reading view and indexed sections"
            >
              <Layers className="h-3.5 w-3.5" />
              {showSections ? "Reading View" : `Sections (${document.chunks.length})`}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {!showSections ? (
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <MarkdownAnswer content={stitchedText} />
          </div>
        ) : (
          <div className="space-y-3">
            {document.chunks.map((chunk) => (
              <div
                key={chunk.chunk_id}
                className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-xs leading-relaxed text-slate-200"
              >
                <div className="mb-1 font-mono text-[10px] text-slate-500">
                  Section #{chunk.chunk_index + 1}
                </div>
                <p className="whitespace-pre-wrap">{chunk.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
