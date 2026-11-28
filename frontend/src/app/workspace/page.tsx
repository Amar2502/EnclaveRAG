"use client";

import {
  AlertTriangle,
  Check,
  Copy,
  Eye,
  FileText,
  FolderOpen,
  History,
  Lock,
  MessageSquarePlus,
  Search,
  Send,
  Sparkles,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";

import { AppNav } from "@/components/AppNav";
import { ClearanceBadge } from "@/components/ClearanceBadge";
import { DocumentModal } from "@/components/DocumentModal";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import {
  ApiError,
  deleteConversation,
  fetchConversationDetail,
  fetchConversations,
  fetchDocumentDetail,
  fetchDocuments,
  fetchSuggestions,
  streamRagQuery,
  uploadDocumentSync,
} from "@/lib/api";
import { clearSession, getSession, type StoredSession } from "@/lib/session";
import type {
  ChatTurn,
  ConversationSummary,
  DocumentDetail,
  DocumentRecord,
} from "@/lib/types";
import { formatTierLabel, useAppStore } from "@/store/useAppStore";

const NO_INFO_SENTINEL = "No accessible information was found for your query.";

export default function WorkspacePage() {
  const router = useRouter();
  const [session, setSession] = useState<StoredSession | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [queryInput, setQueryInput] = useState("");
  const [modalDoc, setModalDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [mobileDrawer, setMobileDrawer] = useState<"none" | "chats" | "docs">("none");
  const [dragActive, setDragActive] = useState(false);

  const clearanceLabels = useAppStore((s) => s.clearanceLabels);
  const setClearanceLabels = useAppStore((s) => s.setClearanceLabels);
  const abortRef = useRef<AbortController | null>(null);

  // Sidebar search & filter
  const [docSearch, setDocSearch] = useState("");
  const [deptFilter, setDeptFilter] = useState("ALL");
  const [tierFilter, setTierFilter] = useState<number>(0);

  // Team upload modal
  const [showUpload, setShowUpload] = useState(false);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadDept, setUploadDept] = useState("General");
  const [uploadClearance, setUploadClearance] = useState(1);
  const [uploadReplace, setUploadReplace] = useState(true);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const chatEndRef = useRef<HTMLDivElement | null>(null);

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

  const refreshWorkspaceData = useCallback(
    async (token: string) => {
      const [docs, convs, suggs] = await Promise.all([
        fetchDocuments(token),
        fetchConversations(token),
        fetchSuggestions(token),
      ]);
      setDocuments(docs);
      setConversations(convs);
      setSuggestions(suggs);
    },
    [],
  );

  useEffect(() => {
    const active = getSession();
    if (!active) {
      router.push("/login");
      return;
    }
    setSession(active);
    if (active.user.clearance_labels) {
      setClearanceLabels(active.user.clearance_labels);
    }
    setUploadDept(active.user.department || "General");
    setUploadClearance(Math.min(2, active.user.clearance_level));

    void refreshWorkspaceData(active.access_token).catch((err) => {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to load workspace.");
      }
    });
  }, [handleAuthError, refreshWorkspaceData, router, setClearanceLabels]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingAnswer]);

  const departments = useMemo(() => {
    const set = new Set<string>();
    for (const doc of documents) {
      set.add(doc.department);
    }
    return Array.from(set).sort();
  }, [documents]);

  const filteredDocs = useMemo(() => {
    const q = docSearch.trim().toLowerCase();
    return documents.filter((doc) => {
      if (deptFilter !== "ALL" && doc.department !== deptFilter) return false;
      if (tierFilter > 0 && doc.clearance_level !== tierFilter) return false;
      if (q && !doc.title.toLowerCase().includes(q) && !doc.department.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [deptFilter, docSearch, documents, tierFilter]);

  async function submitQuestion(text: string) {
    if (!session || !text.trim() || loading) return;
    const trimmed = text.trim();
    const priorHistory = messages;
    const controller = new AbortController();
    abortRef.current = controller;

    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setQueryInput("");
    setStreamingAnswer("");
    setLoading(true);
    setError(null);

    try {
      await streamRagQuery(session.access_token, {
        query: trimmed,
        history: priorHistory,
        conversationId: activeConversationId,
        signal: controller.signal,
        onToken: (tok) => {
          setStreamingAnswer((prev) => prev + tok);
        },
        onDone: (done) => {
          setStreamingAnswer("");
          setActiveConversationId(done.conversation_id);
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: done.answer,
              citations: done.citations,
            },
          ]);
          void fetchConversations(session.access_token).then(setConversations);
        },
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setStreamingAnswer((partial) => {
          if (partial.trim()) {
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: `${partial.trim()}\n\n*(Stopped)*` },
            ]);
          }
          return "";
        });
        return;
      }
      setStreamingAnswer("");
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Query failed.");
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  }

  function handleStopStreaming() {
    abortRef.current?.abort();
  }

  function handleCopyAnswer(content: string, idx: number) {
    void navigator.clipboard.writeText(content);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx((prev) => (prev === idx ? null : prev)), 1500);
  }

  function handleDropFile(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragActive(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) {
      setUploadFile(dropped);
    }
  }

  function handleQuery(event: FormEvent) {
    event.preventDefault();
    void submitQuestion(queryInput);
  }

  async function handleSelectConversation(convId: string) {
    if (!session) return;
    setError(null);
    try {
      const detail = await fetchConversationDetail(session.access_token, convId);
      setActiveConversationId(detail.id);
      setMessages(detail.messages);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Failed to load conversation.");
      }
    }
  }

  async function handleDeleteConversation(convId: string) {
    if (!session) return;
    try {
      await deleteConversation(session.access_token, convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConversationId === convId) {
        setActiveConversationId(null);
        setMessages([]);
      }
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Could not delete conversation.");
      }
    }
  }

  function startNewChat() {
    setActiveConversationId(null);
    setMessages([]);
    setStreamingAnswer("");
    setError(null);
  }

  async function handleViewDoc(docId: string) {
    if (!session) return;
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

  async function handleTeamUpload(event: FormEvent) {
    event.preventDefault();
    if (!session || !uploadFile) return;
    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("clearance_level", String(uploadClearance));
      formData.append("department", uploadDept);
      if (uploadTitle.trim()) {
        formData.append("title", uploadTitle.trim());
      }
      formData.append("replace_existing", String(uploadReplace));

      await uploadDocumentSync(session.access_token, formData);
      setShowUpload(false);
      setUploadTitle("");
      setUploadFile(null);
      await refreshWorkspaceData(session.access_token);
    } catch (err) {
      if (!handleAuthError(err)) {
        setError(err instanceof Error ? err.message : "Upload failed.");
      }
    } finally {
      setUploading(false);
    }
  }

  if (!session) {
    return <div className="min-h-screen bg-[#060a12]" />;
  }

  const departmentChoices = Array.from(
    new Set(["General", session.user.department || "General"]),
  );

  return (
    <div className="min-h-screen bg-[#060a12] text-slate-100">
      <AppNav user={session.user} token={session.access_token} />

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-5 px-4 py-6 lg:grid-cols-12">
        {/* Mobile Drawer Toggles */}
        <div className="flex items-center justify-between gap-2 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileDrawer((d) => (d === "chats" ? "none" : "chats"))}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-[#0b111e] px-3 py-2 text-xs font-semibold text-slate-200"
          >
            <History className="h-3.5 w-3.5 text-sky-400" />
            Chats ({conversations.length})
          </button>
          <button
            type="button"
            onClick={() => setMobileDrawer((d) => (d === "docs" ? "none" : "docs"))}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-[#0b111e] px-3 py-2 text-xs font-semibold text-slate-200"
          >
            <FolderOpen className="h-3.5 w-3.5 text-emerald-400" />
            Knowledge ({filteredDocs.length})
          </button>
        </div>

        {/* Left: Saved Chats */}
        <aside
          className={`space-y-3 lg:col-span-2 lg:block ${
            mobileDrawer === "chats" ? "block" : "hidden"
          }`}
        >
          <button
            type="button"
            onClick={startNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs font-semibold text-sky-200 hover:bg-sky-500/20"
          >
            <MessageSquarePlus className="h-4 w-4" />
            New Chat
          </button>

          <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-3">
            <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Recent Chats
            </h2>
            {conversations.length === 0 ? (
              <p className="text-xs text-slate-500">Your saved chats will appear here.</p>
            ) : (
              <div className="space-y-1">
                {conversations.map((conv) => (
                  <div
                    key={conv.id}
                    className={`group flex items-center justify-between gap-1 rounded-lg px-2 py-1.5 text-xs ${
                      activeConversationId === conv.id
                        ? "bg-sky-500/15 text-sky-200"
                        : "text-slate-300 hover:bg-slate-900"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void handleSelectConversation(conv.id)}
                      className="flex-1 truncate text-left"
                      title={conv.title}
                    >
                      {conv.title}
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDeleteConversation(conv.id)}
                      className="opacity-0 text-slate-500 hover:text-rose-400 group-hover:opacity-100"
                      title="Delete conversation"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Center: Multi-Turn Chat Thread */}
        <section className="flex flex-col space-y-4 lg:col-span-6">
          <div className="flex items-center justify-between rounded-2xl border border-slate-800 bg-[#0b111e] px-4 py-3 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5 text-emerald-400" />
              Scoped to {session.user.org_name} · {session.user.department}
            </span>
            <ClearanceBadge level={session.user.clearance_level} />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3.5 text-xs text-rose-200">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex min-h-[420px] max-h-[62vh] flex-col gap-4 overflow-y-auto rounded-2xl border border-slate-800 bg-[#0b111e] p-4">
            {messages.length === 0 && !streamingAnswer ? (
              <div className="my-auto space-y-4 py-6 text-center">
                <div className="mx-auto inline-flex items-center gap-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs text-sky-300">
                  <Sparkles className="h-3.5 w-3.5" />
                  Ask anything across your permitted knowledge base
                </div>
                {suggestions.length > 0 && (
                  <div className="mx-auto flex max-w-lg flex-wrap justify-center gap-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => void submitQuestion(s)}
                        className="rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-left text-xs text-slate-200 hover:border-sky-500/60 hover:text-white"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <>
                {messages.map((turn, idx) => (
                  <div
                    key={`${turn.role}-${idx}`}
                    className={`rounded-2xl p-4 ${
                      turn.role === "user"
                        ? "ml-8 border border-sky-500/30 bg-sky-500/10 text-sm text-white"
                        : "mr-4 border border-slate-800 bg-slate-950/70"
                    }`}
                  >
                    {turn.role === "user" ? (
                      <p className="whitespace-pre-wrap">{turn.content}</p>
                    ) : (
                      <>
                        <div className="mb-1 flex justify-end">
                          <button
                            type="button"
                            onClick={() => handleCopyAnswer(turn.content, idx)}
                            className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:text-white"
                            title="Copy answer"
                          >
                            {copiedIdx === idx ? (
                              <>
                                <Check className="h-3 w-3 text-emerald-400" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-3 w-3" />
                                Copy
                              </>
                            )}
                          </button>
                        </div>
                        <MarkdownAnswer content={turn.content} />
                        {turn.content === NO_INFO_SENTINEL && suggestions.length > 0 && (
                          <div className="mt-3 border-t border-slate-800 pt-2.5">
                            <div className="mb-1.5 text-[11px] text-slate-400">
                              Try asking about documents you can access:
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {suggestions.map((s) => (
                                <button
                                  key={s}
                                  type="button"
                                  onClick={() => void submitQuestion(s)}
                                  className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-[11px] text-sky-300 hover:border-sky-500/60"
                                >
                                  {s}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                        {turn.citations && turn.citations.length > 0 && (
                          <div className="mt-3 border-t border-slate-800 pt-2.5">
                            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                              Sources ({turn.citations.length})
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {turn.citations.map((cit) => (
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
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}

                {streamingAnswer && (
                  <div className="mr-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <MarkdownAnswer content={streamingAnswer} />
                  </div>
                )}
              </>
            )}
            <div ref={chatEndRef} />
          </div>

          <form
            onSubmit={handleQuery}
            className="flex gap-2 rounded-2xl border border-slate-800 bg-[#0b111e] p-3"
          >
            <input
              type="text"
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="Ask a question or follow up..."
              className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-sm text-white outline-none focus:border-sky-500"
            />
            {loading ? (
              <button
                type="button"
                onClick={handleStopStreaming}
                className="inline-flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-500"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!queryInput.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                Ask
              </button>
            )}
          </form>
        </section>

        {/* Right: Accessible Knowledge Sidebar */}
        <aside
          className={`lg:col-span-4 lg:block ${
            mobileDrawer === "docs" ? "block" : "hidden"
          }`}
        >
          <div className="rounded-2xl border border-slate-800 bg-[#0b111e] p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-white">
                Accessible Knowledge ({filteredDocs.length})
              </h2>
              <button
                type="button"
                onClick={() => setShowUpload(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-xs font-medium text-sky-200 hover:bg-sky-500/20"
              >
                <Upload className="h-3.5 w-3.5" />
                Upload Doc
              </button>
            </div>

            <div className="mb-3 space-y-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
                <input
                  type="text"
                  value={docSearch}
                  onChange={(e) => setDocSearch(e.target.value)}
                  placeholder="Search documents..."
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 py-1.5 pl-8 pr-3 text-xs text-white outline-none focus:border-sky-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={deptFilter}
                  onChange={(e) => setDeptFilter(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
                >
                  <option value="ALL">All Departments</option>
                  {departments.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
                <select
                  value={tierFilter}
                  onChange={(e) => setTierFilter(Number(e.target.value))}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
                >
                  <option value={0}>All Access Levels</option>
                  {[1, 2, 3, 4]
                    .filter((lvl) => lvl <= session.user.clearance_level)
                    .map((lvl) => (
                      <option key={lvl} value={lvl}>
                        {formatTierLabel(lvl, clearanceLabels)}
                      </option>
                    ))}
                </select>
              </div>
            </div>

            {filteredDocs.length === 0 ? (
              <p className="text-xs text-slate-500">No matching documents at your tier.</p>
            ) : (
              <div className="max-h-[58vh] space-y-2 overflow-y-auto pr-1">
                {filteredDocs.map((doc) => (
                  <div
                    key={doc.id}
                    className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-1.5 font-semibold text-slate-100">
                          <span>{doc.title}</span>
                          {doc.version && doc.version > 1 && (
                            <span className="rounded bg-sky-500/15 px-1 py-0.5 text-[10px] text-sky-300">
                              v{doc.version}
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 text-[11px] text-slate-400">
                          {doc.department}
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

      {showUpload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-[#0d1424] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-bold text-white">Upload Team Document</h3>
              <button
                type="button"
                onClick={() => setShowUpload(false)}
                className="rounded-lg border border-slate-700 p-1 text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <form onSubmit={handleTeamUpload} className="space-y-3 text-xs">
              <div>
                <label className="mb-1 block text-slate-300">Document File (.pdf, .md, .txt)</label>
                <label
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragActive(true);
                  }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={handleDropFile}
                  className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed p-4 text-center transition ${
                    dragActive
                      ? "border-sky-400 bg-sky-500/10"
                      : "border-slate-700 bg-slate-950 hover:border-slate-500"
                  }`}
                >
                  <Upload className="mb-1.5 h-5 w-5 text-sky-400" />
                  {uploadFile ? (
                    <span className="font-medium text-slate-100">
                      {uploadFile.name} ({Math.max(1, Math.round(uploadFile.size / 1024))} KB)
                    </span>
                  ) : (
                    <span className="text-slate-400">
                      Drag & drop a file here, or click to browse (max 10 MB)
                    </span>
                  )}
                  <input
                    type="file"
                    accept=".pdf,.md,.txt"
                    className="hidden"
                    onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  />
                </label>
              </div>
              <div>
                <label className="mb-1 block text-slate-300">Document Title (optional)</label>
                <input
                  type="text"
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                  placeholder="Defaults to filename"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="mb-1 block text-slate-300">Department</label>
                  <select
                    value={uploadDept}
                    onChange={(e) => setUploadDept(e.target.value)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-white"
                  >
                    {departmentChoices.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-slate-300">Access Level</label>
                  <select
                    value={uploadClearance}
                    onChange={(e) => setUploadClearance(Number(e.target.value))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-white"
                  >
                    {[1, 2, 3, 4]
                      .filter((lvl) => lvl <= session.user.clearance_level)
                      .map((lvl) => (
                        <option key={lvl} value={lvl}>
                          {formatTierLabel(lvl, clearanceLabels)}
                        </option>
                      ))}
                  </select>
                </div>
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
                disabled={uploading || !uploadFile}
                className="w-full rounded-xl bg-sky-600 py-2 font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
              >
                {uploading ? "Uploading..." : "Upload Document"}
              </button>
            </form>
          </div>
        </div>
      )}

      <DocumentModal
        document={modalDoc}
        token={session.access_token}
        onClose={() => setModalDoc(null)}
      />
    </div>
  );
}
