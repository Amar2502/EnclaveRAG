export interface AuthUser {
  user_id: string;
  org_id: string;
  org_name: string;
  email: string;
  full_name: string;
  role_title: string;
  department: string;
  clearance_level: number;
  is_org_admin: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface Persona {
  user_id: string;
  org_id: string;
  org_name: string;
  org_slug?: string;
  email: string;
  full_name: string;
  role_title: string;
  department: string;
  clearance_level: number;
  is_org_admin?: boolean;
}

export interface PersonaTokenResponse {
  access_token: string;
  token_type: string;
  persona: Persona;
}

export interface OrgUser {
  id: string;
  email: string;
  full_name: string;
  role_title: string;
  department: string;
  clearance_level: number;
  is_org_admin: boolean;
  is_active: boolean;
  token_version: number;
  created_at: string;
}

export interface InvitationRecord {
  id: string;
  org_id?: string;
  email: string;
  role_title: string;
  department: string;
  clearance_level: number;
  expires_at: string;
  accepted_at?: string | null;
  created_at: string;
  invite_token?: string;
  invite_url?: string;
}

export interface DocumentRecord {
  id: string;
  org_id: string;
  title: string;
  department: string;
  clearance_level: number;
  classification_tag: string;
  source_uri: string;
  created_at: string;
  updated_at: string;
  chunk_count?: number;
}

export interface DocumentDetail extends DocumentRecord {
  chunks: Array<{
    chunk_id: string;
    chunk_index: number;
    content: string;
  }>;
}

export interface IngestionJob {
  id: string;
  org_id: string;
  document_id: string | null;
  title: string;
  department: string;
  clearance_level: number;
  filename: string;
  storage_key: string;
  status: "queued" | "processing" | "indexed" | "failed";
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface BillingUsage {
  org_id: string;
  plan_tier: "free" | "pro" | "enterprise";
  period_ym: string;
  max_documents: number;
  documents_count: number;
  monthly_query_limit: number;
  queries_used: number;
  tokens_used: number;
}

export interface Citation {
  document_id: string;
  document_title: string;
  department: string;
  clearance_level: number;
  classification_tag: string;
}

export interface TraceChunk {
  chunk_id: string;
  document_id: string;
  document_title: string;
  department: string;
  clearance_level: number;
  classification_tag: string;
  chunk_index: number;
  snippet: string;
  vector_score: number | null;
  fts_score: number | null;
  rrf_score: number;
}

export interface QueryTrace {
  rls_context: {
    org_id: string;
    user_id: string;
    clearance_level: number;
    department: string;
  };
  retrieval: {
    iterative_scan_enabled: boolean;
    vector_candidates: number;
    fts_candidates: number;
    fused_count: number;
    chunks: TraceChunk[];
  };
  timings_ms: {
    embed: number;
    retrieval: number;
    llm: number;
    total: number;
  };
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  trace: QueryTrace;
}

export interface AuditLogEntry {
  id: string;
  org_id: string;
  user_id: string;
  user_clearance: number;
  query_text: string;
  retrieved_doc_ids: string[];
  latency_ms: number;
  created_at: string;
}

export const CLEARANCE_LABELS: Record<number, { tag: string; style: string }> = {
  1: {
    tag: "L1 PUBLIC",
    style: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  },
  2: {
    tag: "L2 INTERNAL",
    style: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  },
  3: {
    tag: "L3 CONFIDENTIAL",
    style: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  },
  4: {
    tag: "L4 EXECUTIVE",
    style: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  },
};
