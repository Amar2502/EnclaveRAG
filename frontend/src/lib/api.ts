import type {
  AuditLogEntry,
  DocumentDetail,
  DocumentRecord,
  Persona,
  PersonaTokenResponse,
  QueryResponse,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

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
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function authHeaders(token: string, extra?: Record<string, string>): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    ...extra,
  };
}

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
): Promise<DocumentRecord> {
  const data = await request<{ document: DocumentRecord }>(
    `/api/v1/documents/${documentId}/classification`,
    {
      method: "PATCH",
      headers: authHeaders(token, { "Content-Type": "application/json" }),
      body: JSON.stringify({ clearance_level: clearanceLevel }),
    },
  );
  return data.document;
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

export async function fetchAuditLogs(token: string, limit = 25): Promise<AuditLogEntry[]> {
  const data = await request<{ audit_logs: AuditLogEntry[] }>(
    `/api/v1/audit?limit=${limit}`,
    { headers: authHeaders(token) },
  );
  return data.audit_logs;
}
