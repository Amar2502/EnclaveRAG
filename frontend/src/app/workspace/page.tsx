"use client";

import { AlertTriangle, Eye, FileText, Lock, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AppNav } from "@/components/AppNav";
import { ClearanceBadge } from "@/components/ClearanceBadge";
import { DocumentModal } from "@/components/DocumentModal";
import {
  ApiError,
  fetchDocumentDetail,
  fetchDocuments,
  runRagQuery,
} from "@/lib/api";
import { clearSession, getSession, type StoredSession } from "@/lib/session";
import type { DocumentDetail, DocumentRecord, QueryResponse } from "@/lib/types";

export default function WorkspacePage() {
  const router = useRouter();
  const [session, setSession] = useState<StoredSession | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [queryInput, setQueryInput] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [modalDoc, setModalDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAuthError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        router.push("/login?revoked=1");
        return true;
      }
      return false;
    },
    [router],
  );

  useEffect(() => {
    const active = getSession();
    if (!active) {
      router.push("/login");
      return;
    }
    setSession(active);
    void fetchDocuments(active.access_token)
      .then(setDocuments)
      .catch((err) => {
        if (!handleAuthError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load documents.");
        }
      });
  }, [handleAuthError, router]);

  async function handleQuery(event: FormEvent) {
    event.preventDefault();
    if (!session || !queryInput.trim()) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await runRagQuery(session.access_token, queryInput);
      setResult(res);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Query failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleViewDoc(docId: string) {
    if (!session) {
      return;
    }
    setError(null);
    try {
      const detail = await fetchDocumentDetail(session.access_token, docId);
      setModalDoc(detail);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Document access denied.");
      }
    }
  }

  if (!session) {
    return <div className="min-h-screen bg-[#060a12]" />;
  }

  return (
    <div className="min-h-screen bg-[#060a12] text-slate-100">
      <AppNav user={session.user} token={session.access_token} />

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 py-6 lg:grid-cols-12">
        <section className="space-y-5 lg:col-span-8">
          <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-5">
            <div className="mb-3 flex items-center justify-between text-xs text-slate-400">
              <span className="inline-flex items-center gap-1.5">
                <Lock className="h-3.5 w-3.5 text-emerald-400" />
                Scoped to {session.user.org_name} · {session.user.department}
              </span>
              <ClearanceBadge level={session.user.clearance_level} />
            </div>

            <form onSubmit={handleQuery} className="flex gap-2">
              <input
                type="text"
                value={queryInput}
                onChange={(e) => setQueryInput(e.target.value)}
                placeholder="Ask a question across your permitted company documents..."
                className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-sm text-white outline-none focus:border-sky-500"
              />
              <button
                type="submit"
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-xl bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                {loading ? "Searching..." : "Ask"}
              </button>
            </form>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-5">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-100">
                {result.answer}
              </p>

              <div className="mt-4 border-t border-slate-800 pt-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Sources ({result.citations.length})
                </div>
                {result.citations.length === 0 ? (
                  <p className="text-xs text-slate-500">No citations returned.</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {result.citations.map((cit) => (
                      <button
                        key={cit.document_id}
                        type="button"
                        onClick={() => void handleViewDoc(cit.document_id)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-sky-300 hover:border-sky-500/60"
                      >
                        <FileText className="h-3.5 w-3.5" />
                        <span>{cit.document_title}</span>
                        <ClearanceBadge level={cit.clearance_level} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </section>

        <aside className="lg:col-span-4">
          <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-4">
            <h2 className="mb-3 text-sm font-semibold text-white">
              Accessible Knowledge ({documents.length})
            </h2>
            {documents.length === 0 ? (
              <p className="text-xs text-slate-500">No documents available at your tier yet.</p>
            ) : (
              <div className="space-y-2">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs"
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
                    <button
                      type="button"
                      onClick={() => void handleViewDoc(doc.id)}
                      className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-sky-300 hover:text-sky-200"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      Open Document
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </main>

      <DocumentModal document={modalDoc} onClose={() => setModalDoc(null)} />
    </div>
  );
}
