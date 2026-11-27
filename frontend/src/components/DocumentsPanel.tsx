"use client";

import { Eye, FilePlus2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { DocumentRecord } from "@/lib/types";
import { ClearanceBadge } from "./ClearanceBadge";

interface DocumentsPanelProps {
  documents: DocumentRecord[];
  userClearance: number;
  busy: boolean;
  onViewDocument: (docId: string) => void;
  onReclassify: (docId: string, newLevel: number) => Promise<void>;
  onIngest: (payload: {
    title: string;
    department: string;
    clearance_level: number;
    content: string;
  }) => Promise<void>;
}

export function DocumentsPanel({
  documents,
  userClearance,
  busy,
  onViewDocument,
  onReclassify,
  onIngest,
}: DocumentsPanelProps) {
  const [showIngest, setShowIngest] = useState(false);
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("Engineering");
  const [clearance, setClearance] = useState(Math.min(2, userClearance));
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleIngestSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await onIngest({
        title,
        department,
        clearance_level: clearance,
        content,
      });
      setTitle("");
      setContent("");
      setShowIngest(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to ingest document.");
    }
  }

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <p className="text-slate-400">
          Visible via RLS (<span className="font-semibold text-white">{documents.length}</span>{" "}
          documents)
        </p>
        <button
          type="button"
          onClick={() => {
            setClearance(Math.min(clearance, userClearance));
            setShowIngest((prev) => !prev);
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-medium text-slate-200 hover:border-slate-600"
        >
          <FilePlus2 className="h-3.5 w-3.5 text-emerald-400" />
          {showIngest ? "Cancel" : "Ingest Doc"}
        </button>
      </div>

      {showIngest && (
        <form
          onSubmit={handleIngestSubmit}
          className="space-y-2.5 rounded-xl border border-slate-800 bg-slate-900/70 p-3"
        >
          <input
            required
            placeholder="Document title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              required
              placeholder="Department"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500"
            />
            <select
              value={clearance}
              onChange={(e) => setClearance(Number(e.target.value))}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500"
            >
              {[1, 2, 3, 4].map((lvl) => (
                <option key={lvl} value={lvl} disabled={lvl > userClearance}>
                  L{lvl} {lvl > userClearance ? "(above your clearance)" : ""}
                </option>
              ))}
            </select>
          </div>
          <textarea
            required
            rows={3}
            placeholder="Document content to chunk & embed via Gemini..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500"
          />
          {error && <p className="text-rose-400">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-emerald-600 px-3 py-1.5 font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {busy ? "Embedding & Saving..." : "Embed & Store Under RLS"}
          </button>
        </form>
      )}

      <div className="space-y-2">
        {documents.map((doc) => (
          <div
            key={doc.id}
            className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold text-slate-100">{doc.title}</div>
                <div className="mt-0.5 text-[11px] text-slate-400">
                  {doc.department} · {doc.chunk_count ?? 1} chunk(s)
                </div>
              </div>
              <ClearanceBadge level={doc.clearance_level} />
            </div>

            <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800/70 pt-2">
              <button
                type="button"
                onClick={() => onViewDocument(doc.id)}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-sky-300 hover:text-sky-200"
              >
                <Eye className="h-3.5 w-3.5" />
                View via RLS Proxy
              </button>

              <div className="flex items-center gap-1">
                <span className="text-[10px] text-slate-500">O(1) Tier:</span>
                {[1, 2, 3, 4].map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    disabled={busy || lvl > userClearance || lvl === doc.clearance_level}
                    onClick={() => void onReclassify(doc.id, lvl)}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold transition ${
                      lvl === doc.clearance_level
                        ? "bg-slate-700 text-white"
                        : lvl > userClearance
                          ? "cursor-not-allowed text-slate-600"
                          : "border border-slate-700 text-slate-300 hover:border-slate-500 hover:text-white"
                    }`}
                  >
                    L{lvl}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
