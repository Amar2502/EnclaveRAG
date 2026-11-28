"use client";

import {
  AlertTriangle,
  Copy,
  Download,
  RefreshCw,
  Search,
  Send,
  Trash2,
  UploadCloud,
  UserPlus,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AppNav } from "@/components/AppNav";
import { ClearanceBadge } from "@/components/ClearanceBadge";
import { ConfirmModal } from "@/components/ConfirmModal";
import { DocumentModal } from "@/components/DocumentModal";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { XRayPanel } from "@/components/XRayPanel";
import {
  ApiError,
  cancelAdminInvite,
  createAdminInvite,
  deleteDocument,
  fetchAdminInvites,
  fetchAdminUsers,
  fetchAuditLogs,
  fetchBillingUsage,
  fetchDocumentDetail,
  fetchDocuments,
  fetchJobs,
  fetchOrgSettings,
  reclassifyDocument,
  resendAdminInvite,
  revokeAdminUser,
  runRagQuery,
  updateAdminUser,
  updateOrgSettings,
  uploadDocumentAsync,
} from "@/lib/api";
import { clearSession, getSession, saveSession, type StoredSession } from "@/lib/session";
import { formatTierLabel, useAppStore } from "@/store/useAppStore";
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
  const [uploadReplace, setUploadReplace] = useState(true);

  // Policy X-Ray debugger state
  const [debugQuery, setDebugQuery] = useState("");
  const [debugResult, setDebugResult] = useState<QueryResponse | null>(null);

  // UX-4: Search, pagination, confirm dialog, and editable org tier labels
  const [memberSearch, setMemberSearch] = useState("");
  const [docSearch, setDocSearch] = useState("");
  const [auditSearch, setAuditSearch] = useState("");
  const [auditLimit, setAuditLimit] = useState(20);
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    confirmLabel: string;
    onConfirm: () => Promise<void>;
  } | null>(null);
  const clearanceLabels = useAppStore((s) => s.clearanceLabels);
  const setClearanceLabels = useAppStore((s) => s.setClearanceLabels);
  const [labelDraft, setLabelDraft] = useState<Record<string, string>>(clearanceLabels);
  const [labelsSaved, setLabelsSaved] = useState(false);

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
      const [u, inv, docs, jobList, logs, bill, orgSettings] = await Promise.all([
        fetchAdminUsers(token),
        fetchAdminInvites(token),
        fetchDocuments(token),
        fetchJobs(token),
        fetchAuditLogs(token, 100),
        fetchBillingUsage(token),
        fetchOrgSettings(token),
      ]);
      setUsers(u);
      setInvites(inv);
      setDocuments(docs);
      setJobs(jobList);
      setAuditLogs(logs);
      setUsage(bill);
      setClearanceLabels(orgSettings.clearance_labels);
      setLabelDraft(orgSettings.clearance_labels);
    },
    [setClearanceLabels],
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

  useEffect(() => {
    if (!session) return;
    const hasPendingJobs = jobs.some(
      (j) => j.status === "queued" || j.status === "processing",
    );
    if (!hasPendingJobs) return;
    const timer = setInterval(() => {
      void loadAll(session.access_token);
    }, 2000);
    return () => clearInterval(timer);
  }, [jobs, loadAll, session]);

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
        setError(err instanceof Error ? err.message : "Failed to sign user out.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleUserDepartment(userId: string, department: string) {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      await updateAdminUser(session.access_token, userId, { department });
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to update department.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleToggleAdmin(u: OrgUser) {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      await updateAdminUser(session.access_token, u.id, { is_org_admin: !u.is_org_admin });
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to update admin role.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleCancelInvite(inviteId: string) {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      await cancelAdminInvite(session.access_token, inviteId);
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to cancel invite.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleResendInvite(inviteId: string) {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await resendAdminInvite(session.access_token, inviteId);
      setLatestInviteUrl(updated.invite_url ?? null);
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to resend invite.");
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
      formData.append("replace_existing", String(uploadReplace));
      if (uploadTitle.trim()) {
        formData.append("title", uploadTitle.trim());
      }
      await uploadDocumentAsync(session.access_token, formData);
      setUploadFile(null);
      setUploadTitle("");
      await loadAll(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Document upload failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleReclassify(docId: string, level: number, department?: string) {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await reclassifyDocument(session.access_token, docId, level, department);
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
    const header = "id,user_name,user_email,user_id,user_clearance,latency_ms,created_at,query_text\n";
    const rows = auditLogs
      .map(
        (l) =>
          `"${l.id}","${(l.user_name ?? "").replaceAll('"', '""')}","${(l.user_email ?? "").replaceAll('"', '""')}","${l.user_id}",${l.user_clearance},${l.latency_ms},"${l.created_at}","${l.query_text.replaceAll('"', '""')}"`,
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

  async function handleSaveTierLabels(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setLoading(true);
    setLabelsSaved(false);
    setError(null);
    try {
      const res = await updateOrgSettings(session.access_token, labelDraft);
      setClearanceLabels(res.clearance_labels);
      setLabelDraft(res.clearance_labels);
      const nextSession: StoredSession = {
        ...session,
        user: { ...session.user, clearance_labels: res.clearance_labels },
      };
      saveSession(nextSession);
      setSession(nextSession);
      setLabelsSaved(true);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to save tier labels.");
      }
    } finally {
      setLoading(false);
    }
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

  const orgDepartments = Array.from(
    new Set([
      "General",
      "Engineering",
      "HR",
      "Finance",
      "Legal",
      "Operations",
      ...users.map((u) => u.department),
      ...documents.map((d) => d.department),
    ]),
  ).sort();

  const filteredUsers = users.filter((u) => {
    const q = memberSearch.trim().toLowerCase();
    if (!q) return true;
    return (
      u.full_name.toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q) ||
      u.department.toLowerCase().includes(q)
    );
  });

  const filteredDocs = documents.filter((d) => {
    const q = docSearch.trim().toLowerCase();
    if (!q) return true;
    return d.title.toLowerCase().includes(q) || d.department.toLowerCase().includes(q);
  });

  const filteredAuditLogs = auditLogs.filter((entry) => {
    const q = auditSearch.trim().toLowerCase();
    if (!q) return true;
    return (
      entry.query_text.toLowerCase().includes(q) ||
      (entry.user_name ?? "").toLowerCase().includes(q) ||
      (entry.user_email ?? "").toLowerCase().includes(q)
    );
  });

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
                { id: "docs", label: `Knowledge & Uploads (${documents.length})` },
                { id: "audit", label: `Audit Logs (${auditLogs.length})` },
                { id: "xray", label: "Access Simulator" },
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
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-white">
                  Organization Members ({filteredUsers.length})
                </h2>
                <div className="relative w-56">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-500" />
                  <input
                    type="text"
                    value={memberSearch}
                    onChange={(e) => setMemberSearch(e.target.value)}
                    placeholder="Search members..."
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-2.5 text-xs text-white outline-none focus:border-sky-500"
                  />
                </div>
              </div>
              <div className="space-y-2.5 text-xs">
                {filteredUsers.map((u) => (
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
                        {u.email} · {u.role_title}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <select
                        value={u.department}
                        disabled={loading}
                        onChange={(e) => void handleUserDepartment(u.id, e.target.value)}
                        className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-200"
                        title="Change department"
                      >
                        {Array.from(
                          new Set([
                            "General",
                            "Engineering",
                            "HR",
                            "Finance",
                            "Legal",
                            "Operations",
                            u.department,
                          ]),
                        ).map((dept) => (
                          <option key={dept} value={dept}>
                            {dept}
                          </option>
                        ))}
                      </select>
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
                            onClick={() => void handleToggleAdmin(u)}
                            className="rounded border border-violet-500/40 px-2 py-1 text-[10px] text-violet-300 hover:bg-violet-500/10"
                          >
                            {u.is_org_admin ? "Remove Admin" : "Make Admin"}
                          </button>
                          <button
                            type="button"
                            disabled={loading}
                            onClick={() =>
                              setConfirmState({
                                title: `Sign out ${u.full_name}?`,
                                message:
                                  "This will immediately end all active sessions for this employee. They will need to sign in again.",
                                confirmLabel: "Force Sign-Out",
                                onConfirm: () => handleRevoke(u.id),
                              })
                            }
                            className="rounded border border-amber-500/40 px-2 py-1 text-[10px] text-amber-300 hover:bg-amber-500/10"
                          >
                            Force Sign-Out
                          </button>
                          <button
                            type="button"
                            disabled={loading}
                            onClick={() =>
                              setConfirmState({
                                title: `${u.is_active ? "Disable" : "Enable"} ${u.full_name}?`,
                                message: u.is_active
                                  ? "Disabled accounts cannot sign in or query company documents until re-enabled."
                                  : "Re-enabling allows this employee to sign in again.",
                                confirmLabel: u.is_active ? "Disable Account" : "Enable Account",
                                onConfirm: () => handleToggleActive(u),
                              })
                            }
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
                  <select
                    value={invDept}
                    onChange={(e) => setInvDept(e.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  >
                    {orgDepartments.map((dept) => (
                      <option key={dept} value={dept}>
                        {dept}
                      </option>
                    ))}
                  </select>
                </div>
                <select
                  value={invClearance}
                  onChange={(e) => setInvClearance(Number(e.target.value))}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                >
                  {[1, 2, 3, 4].map((lvl) => (
                    <option key={lvl} value={lvl}>
                      {formatTierLabel(lvl, clearanceLabels)}
                    </option>
                  ))}
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
                      className="flex items-center justify-between gap-2 rounded-lg bg-slate-900/60 px-2.5 py-1.5"
                    >
                      <span className="truncate">
                        {inv.email} ({inv.department} · L{inv.clearance_level})
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {inv.accepted_at ? (
                          <span className="text-emerald-400">Accepted</span>
                        ) : (
                          <>
                            <span className="text-amber-300">Pending</span>
                            <button
                              type="button"
                              disabled={loading}
                              onClick={() => void handleResendInvite(inv.id)}
                              className="rounded border border-sky-500/40 px-1.5 py-0.5 text-[10px] text-sky-300 hover:bg-sky-500/10"
                            >
                              Resend
                            </button>
                            <button
                              type="button"
                              disabled={loading}
                              onClick={() => void handleCancelInvite(inv.id)}
                              className="rounded border border-rose-500/40 px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-rose-500/10"
                            >
                              Cancel
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <form onSubmit={handleSaveTierLabels} className="space-y-2 border-t border-slate-800 pt-4 text-xs">
                <div className="font-semibold text-white">Organization Tier Labels</div>
                <p className="text-[11px] text-slate-400">
                  Customize how access levels L1–L4 appear across your workspace.
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {[1, 2, 3, 4].map((lvl) => (
                    <div key={lvl} className="flex items-center gap-1.5">
                      <span className="w-6 font-mono text-[11px] text-slate-400">L{lvl}</span>
                      <input
                        type="text"
                        required
                        maxLength={40}
                        value={labelDraft[String(lvl)] ?? ""}
                        onChange={(e) =>
                          setLabelDraft((prev) => ({ ...prev, [String(lvl)]: e.target.value }))
                        }
                        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-white outline-none focus:border-sky-500"
                      />
                    </div>
                  ))}
                </div>
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="submit"
                    disabled={loading}
                    className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 font-semibold text-sky-200 hover:bg-sky-500/20"
                  >
                    Save Tier Labels
                  </button>
                  {labelsSaved && (
                    <span className="text-[11px] text-emerald-400">Saved!</span>
                  )}
                </div>
              </form>
            </div>
          </div>
        )}

        {tab === "docs" && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="space-y-3 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-7">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-white">
                  Company Documents ({filteredDocs.length})
                </h2>
                <div className="relative w-56">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-500" />
                  <input
                    type="text"
                    value={docSearch}
                    onChange={(e) => setDocSearch(e.target.value)}
                    placeholder="Search documents..."
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-2.5 text-xs text-white outline-none focus:border-sky-500"
                  />
                </div>
              </div>
              <div className="space-y-2 text-xs">
                {filteredDocs.map((doc) => (
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
                        {doc.version && doc.version > 1 ? ` (v${doc.version})` : ""}
                      </button>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                        <select
                          value={doc.department}
                          disabled={loading}
                          onChange={(e) =>
                            void handleReclassify(doc.id, doc.clearance_level, e.target.value)
                          }
                          className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-200"
                          title="Change document department"
                        >
                          {Array.from(
                            new Set([
                              "General",
                              "Engineering",
                              "HR",
                              "Finance",
                              "Legal",
                              "Operations",
                              doc.department,
                            ]),
                          ).map((dept) => (
                            <option key={dept} value={dept}>
                              {dept}
                            </option>
                          ))}
                        </select>
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
                        onClick={() =>
                          setConfirmState({
                            title: `Delete "${doc.title}"?`,
                            message:
                              "This permanently removes the document and its indexed chunks from search.",
                            confirmLabel: "Delete Document",
                            onConfirm: () => handleDeleteDoc(doc.id),
                          })
                        }
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
                Upload Company Document
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
                  <select
                    value={uploadDept}
                    onChange={(e) => setUploadDept(e.target.value)}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  >
                    {orgDepartments.map((dept) => (
                      <option key={dept} value={dept}>
                        {dept}
                      </option>
                    ))}
                  </select>
                  <select
                    value={uploadClearance}
                    onChange={(e) => setUploadClearance(Number(e.target.value))}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-sky-500"
                  >
                    {[1, 2, 3, 4].map((lvl) => (
                      <option key={lvl} value={lvl}>
                        {formatTierLabel(lvl, clearanceLabels)}
                      </option>
                    ))}
                  </select>
                </div>
                <label className="flex items-center gap-2 text-slate-300">
                  <input
                    type="checkbox"
                    checked={uploadReplace}
                    onChange={(e) => setUploadReplace(e.target.checked)}
                  />
                  Replace existing document if title matches
                </label>
                <button
                  type="submit"
                  disabled={loading || !uploadFile}
                  className="w-full rounded-lg bg-sky-600 px-3 py-2 font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
                >
                  Upload & Index Document
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
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-white">
                Tenant Query Audit Trail ({filteredAuditLogs.length})
              </h2>
              <div className="flex items-center gap-2">
                <div className="relative w-56">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-500" />
                  <input
                    type="text"
                    value={auditSearch}
                    onChange={(e) => setAuditSearch(e.target.value)}
                    placeholder="Search query or employee..."
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-2.5 text-xs text-white outline-none focus:border-sky-500"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleExportAuditCsv}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500"
                >
                  <Download className="h-3.5 w-3.5" />
                  Export CSV
                </button>
              </div>
            </div>
            <div className="space-y-2 text-xs">
              {filteredAuditLogs.slice(0, auditLimit).map((entry) => (
                <div
                  key={entry.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3"
                >
                  <div>
                    <div className="font-medium text-slate-100">{entry.query_text}</div>
                    <div className="mt-0.5 text-[11px] text-slate-400">
                      {entry.user_name ? `${entry.user_name} (${entry.user_email ?? ""})` : entry.user_id}{" "}
                      · {new Date(entry.created_at).toLocaleString()}
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
              {filteredAuditLogs.length > auditLimit && (
                <button
                  type="button"
                  onClick={() => setAuditLimit((n) => n + 20)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-900/60 py-2 text-xs font-medium text-sky-300 hover:text-white"
                >
                  Show more ({filteredAuditLogs.length - auditLimit} remaining)
                </button>
              )}
            </div>
          </div>
        )}

        {tab === "xray" && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="space-y-4 rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-6">
              <h2 className="text-sm font-semibold text-white">Simulate Access & Retrieval</h2>
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
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                  <MarkdownAnswer content={debugResult.answer} />
                </div>
              )}
            </div>
            <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-5 lg:col-span-6">
              <XRayPanel trace={debugResult?.trace ?? null} />
            </div>
          </div>
        )}
      </main>

      <DocumentModal
        document={modalDoc}
        token={session.access_token}
        onClose={() => setModalDoc(null)}
      />

      <ConfirmModal
        open={confirmState !== null}
        title={confirmState?.title ?? ""}
        message={confirmState?.message ?? ""}
        confirmLabel={confirmState?.confirmLabel ?? "Confirm"}
        loading={loading}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          const action = confirmState.onConfirm;
          setConfirmState(null);
          void action();
        }}
      />
    </div>
  );
}
