"use client";

import {
  AlertTriangle,
  Copy,
  Download,
  RefreshCw,
  Send,
  Trash2,
  UploadCloud,
  UserPlus,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AppNav } from "@/components/AppNav";
import { ClearanceBadge } from "@/components/ClearanceBadge";
import { DocumentModal } from "@/components/DocumentModal";
import { XRayPanel } from "@/components/XRayPanel";
import {
  ApiError,
  createAdminInvite,
  deleteDocument,
  fetchAdminInvites,
  fetchAdminUsers,
  fetchAuditLogs,
  fetchBillingUsage,
  fetchDocumentDetail,
  fetchDocuments,
  fetchJobs,
  reclassifyDocument,
  revokeAdminUser,
  runRagQuery,
  updateAdminUser,
  uploadDocumentAsync,
} from "@/lib/api";
import { clearSession, getSession, type StoredSession } from "@/lib/session";
import type {
  AuditLogEntry,
  BillingUsage,
  DocumentDetail,
  DocumentRecord,
  IngestionJob,
  InvitationRecord,
  OrgUser,
  QueryResponse,
} from "@/lib/types";

type AdminTab = "team" | "docs" | "audit" | "xray";

export default function AdminConsolePage() {
  const router = useRouter();
  const [session, setSession] = useState<StoredSession | null>(null);
  const [tab, setTab] = useState<AdminTab>("team");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [invites, setInvites] = useState<InvitationRecord[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [modalDoc, setModalDoc] = useState<DocumentDetail | null>(null);

  // Invite form state
  const [invEmail, setInvEmail] = useState("");
  const [invRole, setInvRole] = useState("Engineer");
  const [invDept, setInvDept] = useState("Engineering");
  const [invClearance, setInvClearance] = useState(2);
  const [latestInviteUrl, setLatestInviteUrl] = useState<string | null>(null);

  // Async upload form state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadDept, setUploadDept] = useState("Engineering");
  const [uploadClearance, setUploadClearance] = useState(2);

  // Policy X-Ray debugger state
  const [debugQuery, setDebugQuery] = useState("");
  const [debugResult, setDebugResult] = useState<QueryResponse | null>(null);

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

  const loadAll = useCallback(
    async (token: string) => {
      const [u, inv, docs, jobList, logs, bill] = await Promise.all([
        fetchAdminUsers(token),
        fetchAdminInvites(token),
        fetchDocuments(token),
        fetchJobs(token),
        fetchAuditLogs(token),
        fetchBillingUsage(token),
      ]);
      setUsers(u);
      setInvites(inv);
      setDocuments(docs);
      setJobs(jobList);
      setAuditLogs(logs);
      setUsage(bill);
    },
    [],
  );

  useEffect(() => {
    const active = getSession();
    if (!active) {
      router.push("/login");
      return;
    }
    if (!active.user.is_org_admin) {
      router.push("/workspace");
      return;
    }
    setSession(active);
    void loadAll(active.access_token).catch((err) => {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to load admin console.");
      }
    });
  }, [handleAuthError, loadAll, router]);

  async function handleInviteSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const created = await createAdminInvite(session.access_token, {
        email: invEmail,
        role_title: invRole,
        department: invDept,
        clearance_level: invClearance,
      });
      setLatestInviteUrl(created.invite_url ?? null);
      setInvEmail("");
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to create invite.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleUserClearance(userId: string, newLevel: number) {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await updateAdminUser(session.access_token, userId, { clearance_level: newLevel });
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to update user.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleToggleActive(u: OrgUser) {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await updateAdminUser(session.access_token, u.id, { is_active: !u.is_active });
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to update user status.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke(userId: string) {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await revokeAdminUser(session.access_token, userId);
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to revoke sessions.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleAsyncUpload(event: FormEvent) {
    event.preventDefault();
    if (!session || !uploadFile) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("clearance_level", String(uploadClearance));
      formData.append("department", uploadDept);
      if (uploadTitle.trim()) {
        formData.append("title", uploadTitle.trim());
      }
      await uploadDocumentAsync(session.access_token, formData);
      setUploadFile(null);
      setUploadTitle("");
      await loadAll(session.access_token);
      setTimeout(() => {
        if (session) {
          void loadAll(session.access_token);
        }
      }, 1500);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Async upload failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleReclassify(docId: string, level: number) {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await reclassifyDocument(session.access_token, docId, level);
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Reclassification failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteDoc(docId: string) {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await deleteDocument(session.access_token, docId);
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Delete failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  function handleExportAuditCsv() {
    const header = "id,user_id,user_clearance,latency_ms,created_at,query_text\n";
    const rows = auditLogs
      .map(
        (l) =>
          `"${l.id}","${l.user_id}",${l.user_clearance},${l.latency_ms},"${l.created_at}","${l.query_text.replaceAll('"', '""')}"`,
      )
      .join("\n");
    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "enclaverag-audit-logs.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handleDebugQuery(event: FormEvent) {
    event.preventDefault();
    if (!session || !debugQuery.trim()) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await runRagQuery(session.access_token, debugQuery);
      setDebugResult(res);
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Query failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  if (!session) {
    return <div className="min-h-screen bg-[#060a12]" />;
  }

  return (
    <div className="min-h-screen bg-[#060a12] text-slate-100">
      <AppNav user={session.user} token={session.access_token} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        {usage && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-4">
              <div className="text-[11px] uppercase tracking-wider text-slate-400">Plan Tier</div>
              <div className="mt-1 text-lg font-bold uppercase text-emerald-300">
                {usage.plan_tier}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-4">
              <div className="text-[11px] uppercase tracking-wider text-slate-400">Documents</div>
              <div className="mt-1 font-mono text-lg font-bold text-white">
                {usage.documents_count} / {usage.max_documents}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-4">
              <div className="text-[11px] uppercase tracking-wider text-slate-400">
                Queries ({usage.period_ym})
              </div>
              <div className="mt-1 font-mono text-lg font-bold text-white">
                {usage.queries_used} / {usage.monthly_query_limit}
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1 rounded-xl border border-slate-800 bg-[#0b111e] p-1 text-xs">
            {(
              [
                { id: "team", label: `Team & Invites (${users.length})` },
                { id: "docs", label: `Knowledge & Jobs (${documents.length})` },
                { id: "audit", label: `Audit Logs (${auditLogs.length})` },
                { id: "xray", label: "Policy X-Ray Debugger" },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={`rounded-lg px-3 py-2 font-semibold transition ${
                  tab === item.id
                    ? "bg-slate-800 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => void loadAll(session.access_token)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {tab === "team" && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="space-y-3 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-7">
              <h2 className="text-sm font-semibold text-white">Organization Members</h2>
              <div className="space-y-2.5 text-xs">
                {users.map((u) => (
                  <div
                    key={u.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3"
                  >
                    <div>
                      <div className="flex items-center gap-2 font-semibold text-white">
                        <span>{u.full_name}</span>
                        {u.is_org_admin && (
                          <span className="rounded bg-violet-500/20 px-1.5 py-0.5 text-[10px] text-violet-300">
                            ADMIN
                          </span>
                        )}
                        {!u.is_active && (
                          <span className="rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] text-rose-300">
                            DISABLED
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {u.email} · {u.department} · tv={u.token_version}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {[1, 2, 3, 4].map((lvl) => (
                        <button
                          key={lvl}
                          type="button"
                          disabled={loading || lvl === u.clearance_level}
                          onClick={() => void handleUserClearance(u.id, lvl)}
                          className={`rounded px-2 py-1 text-[10px] font-semibold ${
                            lvl === u.clearance_level
                              ? "bg-sky-600 text-white"
                              : "border border-slate-700 text-slate-300 hover:border-slate-500"
                          }`}
                        >
                          L{lvl}
                        </button>
                      ))}
                      {u.id !== session.user.user_id && (
                        <>
                          <button
                            type="button"
                            disabled={loading}
                            onClick={() => void handleRevoke(u.id)}
                            className="rounded border border-amber-500/40 px-2 py-1 text-[10px] text-amber-300 hover:bg-amber-500/10"
                          >
                            Revoke JWT
                          </button>
                          <button
                            type="button"
                            disabled={loading}
                            onClick={() => void handleToggleActive(u)}
                            className="rounded border border-rose-500/40 px-2 py-1 text-[10px] text-rose-300 hover:bg-rose-500/10"
                          >
                            {u.is_active ? "Disable" : "Enable"}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-4 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <UserPlus className="h-4 w-4 text-emerald-400" />
                Invite Employee
              </h2>
              <form onSubmit={handleInviteSubmit} className="space-y-3 text-xs">
                <input
                  type="email"
                  required
                  placeholder="employee@company.com"
                  value={invEmail}
                  onChange={(e) => setInvEmail(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                />
                <div className="grid grid-cols-2 gap-2">
                  <input
                    required
                    placeholder="Role Title"
                    value={invRole}
                    onChange={(e) => setInvRole(e.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  />
                  <input
                    required
                    placeholder="Department"
                    value={invDept}
                    onChange={(e) => setInvDept(e.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  />
                </div>
                <select
                  value={invClearance}
                  onChange={(e) => setInvClearance(Number(e.target.value))}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                >
                  <option value={1}>L1 Public</option>
                  <option value={2}>L2 Internal</option>
                  <option value={3}>L3 Confidential (Dept Scoped)</option>
                  <option value={4}>L4 Executive (Dept Scoped)</option>
                </select>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full rounded-lg bg-emerald-600 px-3 py-2 font-semibold text-white hover:bg-emerald-500"
                >
                  Generate One-Time Invite Link
                </button>
              </form>

              {latestInviteUrl && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-[11px]">
                  <div className="mb-1 font-semibold text-emerald-300">Share Invite URL:</div>
                  <div className="flex items-center justify-between gap-2">
                    <code className="truncate text-slate-200">{latestInviteUrl}</code>
                    <button
                      type="button"
                      onClick={() => void navigator.clipboard.writeText(latestInviteUrl)}
                      className="shrink-0 rounded border border-emerald-500/40 p-1 text-emerald-200"
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {invites.length > 0 && (
                <div className="space-y-1.5 border-t border-slate-800 pt-3 text-[11px]">
                  <div className="font-semibold text-slate-400">Recent Invites</div>
                  {invites.map((inv) => (
                    <div
                      key={inv.id}
                      className="flex items-center justify-between rounded-lg bg-slate-900/60 px-2.5 py-1.5"
                    >
                      <span>
                        {inv.email} ({inv.department} · L{inv.clearance_level})
                      </span>
                      <span className={inv.accepted_at ? "text-emerald-400" : "text-amber-300"}>
                        {inv.accepted_at ? "Accepted" : "Pending"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === "docs" && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="space-y-3 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-7">
              <h2 className="text-sm font-semibold text-white">Organization Documents (O(1) Governance)</h2>
              <div className="space-y-2 text-xs">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3"
                  >
                    <div>
                      <button
                        type="button"
                        onClick={() =>
                          void fetchDocumentDetail(session.access_token, doc.id).then(setModalDoc)
                        }
                        className="font-semibold text-sky-300 hover:text-sky-200"
                      >
                        {doc.title}
                      </button>
                      <div className="text-[11px] text-slate-400">
                        {doc.department} · {doc.chunk_count ?? 1} chunk(s)
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <ClearanceBadge level={doc.clearance_level} />
                      {[1, 2, 3, 4].map((lvl) => (
                        <button
                          key={lvl}
                          type="button"
                          disabled={loading || lvl === doc.clearance_level}
                          onClick={() => void handleReclassify(doc.id, lvl)}
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            lvl === doc.clearance_level
                              ? "bg-slate-700 text-white"
                              : "border border-slate-700 text-slate-300 hover:border-slate-500"
                          }`}
                        >
                          L{lvl}
                        </button>
                      ))}
                      <button
                        type="button"
                        disabled={loading}
                        onClick={() => void handleDeleteDoc(doc.id)}
                        className="rounded p-1 text-rose-400 hover:bg-rose-500/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-4 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
                <UploadCloud className="h-4 w-4 text-sky-400" />
                Async Document Upload (R2 / Local)
              </h2>
              <form onSubmit={handleAsyncUpload} className="space-y-3 text-xs">
                <input
                  type="file"
                  required
                  accept=".txt,.md,.pdf"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-300"
                />
                <input
                  placeholder="Optional title override"
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                />
                <div className="grid grid-cols-2 gap-2">
                  <input
                    required
                    placeholder="Department"
                    value={uploadDept}
                    onChange={(e) => setUploadDept(e.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  />
                  <select
                    value={uploadClearance}
                    onChange={(e) => setUploadClearance(Number(e.target.value))}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  >
                    <option value={1}>L1 Public</option>
                    <option value={2}>L2 Internal</option>
                    <option value={3}>L3 Confidential</option>
                    <option value={4}>L4 Executive</option>
                  </select>
                </div>
                <button
                  type="submit"
                  disabled={loading || !uploadFile}
                  className="w-full rounded-lg bg-sky-600 px-3 py-2 font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
                >
                  Enqueue Async Ingestion (202)
                </button>
              </form>

              <div className="space-y-1.5 border-t border-slate-800 pt-3 text-[11px]">
                <div className="font-semibold text-slate-400">Ingestion Jobs</div>
                {jobs.map((job) => (
                  <div
                    key={job.id}
                    className="flex items-center justify-between rounded-lg bg-slate-900/60 px-2.5 py-1.5"
                  >
                    <span className="truncate">{job.title}</span>
                    <span
                      className={`font-semibold uppercase ${
                        job.status === "indexed"
                          ? "text-emerald-400"
                          : job.status === "failed"
                            ? "text-rose-400"
                            : "text-amber-300"
                      }`}
                    >
                      {job.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === "audit" && (
          <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">Tenant Query Audit Trail</h2>
              <button
                type="button"
                onClick={handleExportAuditCsv}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500"
              >
                <Download className="h-3.5 w-3.5" />
                Export CSV
              </button>
            </div>
            <div className="space-y-2 text-xs">
              {auditLogs.map((entry) => (
                <div
                  key={entry.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3"
                >
                  <div>
                    <div className="font-medium text-slate-100">{entry.query_text}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-slate-500">
                      User {entry.user_id} · {entry.created_at}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <ClearanceBadge level={entry.user_clearance} />
                    <span className="font-mono text-[11px] text-slate-400">
                      {entry.latency_ms} ms
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "xray" && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="space-y-4 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-6">
              <h2 className="text-sm font-semibold text-white">Admin Policy X-Ray Test</h2>
              <form onSubmit={handleDebugQuery} className="flex gap-2">
                <input
                  value={debugQuery}
                  onChange={(e) => setDebugQuery(e.target.value)}
                  placeholder="Test a query as Org Admin..."
                  className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-sky-500"
                />
                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500"
                >
                  <Send className="h-4 w-4" />
                  Run
                </button>
              </form>
              {debugResult && (
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-200">
                  {debugResult.answer}
                </div>
              )}
            </div>
            <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-6">
              <XRayPanel trace={debugResult?.trace ?? null} />
            </div>
          </div>
        )}
      </main>

      <DocumentModal document={modalDoc} onClose={() => setModalDoc(null)} />
    </div>
  );
}
