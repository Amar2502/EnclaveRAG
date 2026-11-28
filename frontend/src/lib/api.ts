import type {
  AuditLogEntry,
  AuthResponse,
  BillingUsage,
  ChatTurn,
  Citation,
  ConversationDetail,
  ConversationSummary,
  DocumentDetail,
  DocumentRecord,
  IngestionJob,
  InvitationRecord,
  OrgUser,
  Persona,
  PersonaTokenResponse,
  QueryResponse,
  QueryTrace,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) {
        detail = data.detail;
      }
    } catch {
      // Ignore non-JSON error body
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

function authHeaders(token: string, extra?: Record<string, string>): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    ...extra,
  };
}

// --- SaaS Auth ---
export async function registerOrg(payload: {
  org_name: string;
  full_name: string;
  email: string;
  password: string;
  department: string;
}): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/register-org", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function loginUser(payload: {
  email: string;
  password: string;
}): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function logoutUser(token: string): Promise<void> {
  await request<{ status: string }>("/api/v1/auth/logout", {
    method: "POST",
    headers: authHeaders(token),
  });
}

export async function acceptInvite(payload: {
  token: string;
  full_name: string;
  password: string;
}): Promise<AuthResponse> {
  return request<AuthResponse>("/api/v1/auth/accept-invite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateMyProfile(
  token: string,
  payload: {
    full_name?: string;
    current_password?: string;
    new_password?: string;
  },
): Promise<{ full_name: string }> {
  const data = await request<{ user: { full_name: string } }>("/api/v1/auth/me", {
    method: "PATCH",
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return data.user;
}

export async function requestPasswordReset(email: string): Promise<{ email_sent: boolean }> {
  return request<{ email_sent: boolean }>("/api/v1/auth/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export async function confirmPasswordReset(payload: {
  token: string;
  new_password: string;
}): Promise<void> {
  await request<{ status: string }>("/api/v1/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// --- Dev Demo Mode ---
export async function fetchPersonas(): Promise<Persona[]> {
  const data = await request<{ personas: Persona[] }>("/api/v1/personas");
  return data.personas;
}

export async function issuePersonaToken(email: string): Promise<PersonaTokenResponse> {
  return request<PersonaTokenResponse>("/api/v1/auth/persona-token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

// --- RAG & Documents ---
export async function runRagQuery(
  token: string,
  query: string,
  topK = 5,
): Promise<QueryResponse> {
  return request<QueryResponse>("/api/v1/query", {
    method: "POST",
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({ query, top_k: topK }),
  });
}

export async function streamRagQuery(
  token: string,
  params: {
    query: string;
    topK?: number;
    history?: ChatTurn[];
    conversationId?: string | null;
    signal?: AbortSignal;
    onToken: (text: string) => void;
    onDone: (payload: {
      answer: string;
      citations: Citation[];
      conversation_id: string;
      trace: QueryTrace;
    }) => void;
  },
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/query/stream`, {
    method: "POST",
    signal: params.signal,
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({
      query: params.query,
      top_k: params.topK ?? 5,
      history: params.history?.map((t) => ({ role: t.role, content: t.content })) ?? [],
      ...(params.conversationId ? { conversation_id: params.conversationId } : {}),
    }),
  });

  if (!response.ok || !response.body) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      // Ignore non-JSON error body
    }
    throw new ApiError(detail, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let eventName = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) eventName = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLine = line.slice(6);
      }
      if (!dataLine) continue;
      const parsed = JSON.parse(dataLine) as Record<string, unknown>;
      if (eventName === "token" && typeof parsed.text === "string") {
        params.onToken(parsed.text);
      } else if (eventName === "error") {
        throw new ApiError(
          typeof parsed.detail === "string" ? parsed.detail : "Streaming error",
          503,
        );
      } else if (eventName === "done") {
        params.onDone({
          answer: String(parsed.answer ?? ""),
          citations: (parsed.citations as Citation[]) ?? [],
          conversation_id: String(parsed.conversation_id ?? ""),
          trace: parsed.trace as QueryTrace,
        });
      }
    }
  }
}

export async function fetchConversations(token: string): Promise<ConversationSummary[]> {
  const data = await request<{ conversations: ConversationSummary[] }>(
    "/api/v1/conversations",
    { headers: authHeaders(token) },
  );
  return data.conversations;
}

export async function fetchConversationDetail(
  token: string,
  conversationId: string,
): Promise<ConversationDetail> {
  const data = await request<{ conversation: ConversationDetail }>(
    `/api/v1/conversations/${conversationId}`,
    { headers: authHeaders(token) },
  );
  return data.conversation;
}

export async function deleteConversation(
  token: string,
  conversationId: string,
): Promise<void> {
  await request<{ deleted: boolean }>(`/api/v1/conversations/${conversationId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export async function fetchSuggestions(token: string): Promise<string[]> {
  const data = await request<{ suggestions: string[] }>("/api/v1/suggestions", {
    headers: authHeaders(token),
  });
  return data.suggestions;
}

export async function downloadDocument(
  token: string,
  documentId: string,
  fallbackTitle: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/documents/${documentId}/download`, {
    headers: authHeaders(token),
  });
  if (!response.ok) {
    throw new ApiError("Download unavailable.", response.status);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const data = (await response.json()) as { download_url: string };
    window.open(data.download_url, "_blank", "noopener,noreferrer");
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = fallbackTitle;
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function uploadDocumentSync(
  token: string,
  formData: FormData,
): Promise<DocumentRecord> {
  const data = await request<{ document: DocumentRecord }>("/api/v1/documents/upload", {
    method: "POST",
    headers: authHeaders(token),
    body: formData,
  });
  return data.document;
}

export async function fetchDocuments(token: string): Promise<DocumentRecord[]> {
  const data = await request<{ documents: DocumentRecord[] }>("/api/v1/documents", {
    headers: authHeaders(token),
  });
  return data.documents;
}

export async function fetchDocumentDetail(
  token: string,
  documentId: string,
): Promise<DocumentDetail> {
  const data = await request<{ document: DocumentDetail }>(
    `/api/v1/documents/${documentId}/view`,
    { headers: authHeaders(token) },
  );
  return data.document;
}

export async function reclassifyDocument(
  token: string,
  documentId: string,
  clearanceLevel: number,
  department?: string,
): Promise<DocumentRecord> {
  const data = await request<{ document: DocumentRecord }>(
    `/api/v1/documents/${documentId}/classification`,
    {
      method: "PATCH",
      headers: authHeaders(token, { "Content-Type": "application/json" }),
      body: JSON.stringify({
        clearance_level: clearanceLevel,
        ...(department ? { department } : {}),
      }),
    },
  );
  return data.document;
}

export async function deleteDocument(token: string, documentId: string): Promise<void> {
  await request<{ status: string }>(`/api/v1/documents/${documentId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export async function ingestTextDocument(
  token: string,
  payload: {
    title: string;
    department: string;
    clearance_level: number;
    content: string;
  },
): Promise<DocumentRecord> {
  const data = await request<{ document: DocumentRecord }>("/api/v1/documents", {
    method: "POST",
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return data.document;
}

export async function uploadDocumentAsync(
  token: string,
  formData: FormData,
): Promise<IngestionJob> {
  const data = await request<{ job: IngestionJob }>("/api/v1/documents/upload-async", {
    method: "POST",
    headers: authHeaders(token),
    body: formData,
  });
  return data.job;
}

export async function fetchJobs(token: string): Promise<IngestionJob[]> {
  const data = await request<{ jobs: IngestionJob[] }>("/api/v1/jobs", {
    headers: authHeaders(token),
  });
  return data.jobs;
}

// --- Admin Governance, Audit & Billing ---
export async function fetchAdminUsers(token: string): Promise<OrgUser[]> {
  const data = await request<{ users: OrgUser[] }>("/api/v1/admin/users", {
    headers: authHeaders(token),
  });
  return data.users;
}

export async function updateAdminUser(
  token: string,
  userId: string,
  payload: {
    clearance_level?: number;
    department?: string;
    role_title?: string;
    is_org_admin?: boolean;
    is_active?: boolean;
  },
): Promise<OrgUser> {
  const data = await request<{ user: OrgUser }>(`/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return data.user;
}

export async function revokeAdminUser(token: string, userId: string): Promise<void> {
  await request<{ status: string }>(`/api/v1/admin/users/${userId}/revoke`, {
    method: "POST",
    headers: authHeaders(token),
  });
}

export async function fetchAdminInvites(token: string): Promise<InvitationRecord[]> {
  const data = await request<{ invites: InvitationRecord[] }>("/api/v1/admin/invites", {
    headers: authHeaders(token),
  });
  return data.invites;
}

export async function createAdminInvite(
  token: string,
  payload: {
    email: string;
    role_title: string;
    department: string;
    clearance_level: number;
  },
): Promise<InvitationRecord> {
  const data = await request<{ invite: InvitationRecord }>("/api/v1/admin/invites", {
    method: "POST",
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return data.invite;
}

export async function cancelAdminInvite(token: string, inviteId: string): Promise<void> {
  await request<{ status: string }>(`/api/v1/admin/invites/${inviteId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export async function resendAdminInvite(
  token: string,
  inviteId: string,
): Promise<InvitationRecord> {
  const data = await request<{ invite: InvitationRecord }>(
    `/api/v1/admin/invites/${inviteId}/resend`,
    {
      method: "POST",
      headers: authHeaders(token),
    },
  );
  return data.invite;
}

export async function fetchAuditLogs(token: string, limit = 50): Promise<AuditLogEntry[]> {
  const data = await request<{ audit_logs: AuditLogEntry[] }>(
    `/api/v1/audit?limit=${limit}`,
    { headers: authHeaders(token) },
  );
  return data.audit_logs;
}

export async function fetchBillingUsage(token: string): Promise<BillingUsage> {
  const data = await request<{ usage: BillingUsage }>("/api/v1/billing/usage", {
    headers: authHeaders(token),
  });
  return data.usage;
}

export async function fetchOrgSettings(
  token: string,
): Promise<{ clearance_labels: Record<string, string> }> {
  return request<{ clearance_labels: Record<string, string> }>("/api/v1/admin/org-settings", {
    headers: authHeaders(token),
  });
}

export async function updateOrgSettings(
  token: string,
  clearanceLabels: Record<string, string>,
): Promise<{ clearance_labels: Record<string, string> }> {
  return request<{ clearance_labels: Record<string, string> }>("/api/v1/admin/org-settings", {
    method: "PATCH",
    headers: authHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({ clearance_labels: clearanceLabels }),
  });
}
