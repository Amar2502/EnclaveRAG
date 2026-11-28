"use client";

import { AlertTriangle, X } from "lucide-react";

export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  danger = true,
  loading = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-[#0d1424] p-5 shadow-2xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-500/15 text-rose-400">
              <AlertTriangle className="h-4 w-4" />
            </div>
            <h3 className="text-sm font-bold text-white">{title}</h3>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-700 p-1 text-slate-400 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-5 text-xs leading-relaxed text-slate-300">{message}</p>

        <div className="flex justify-end gap-2 text-xs font-semibold">
          <button
            type="button"
            disabled={loading}
            onClick={onCancel}
            className="rounded-lg border border-slate-700 px-3.5 py-2 text-slate-300 hover:text-white"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={onConfirm}
            className={`rounded-lg px-3.5 py-2 text-white disabled:opacity-50 ${
              danger
                ? "bg-rose-600 hover:bg-rose-500"
                : "bg-sky-600 hover:bg-sky-500"
            }`}
          >
            {loading ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
