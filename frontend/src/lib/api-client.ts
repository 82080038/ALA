/**
 * Klien API untuk berkomunikasi dengan back-end FastAPI.
 * Semua request menyertakan header tenant (X-User-Role, X-Tier-Level,
 * X-Institution-ID, X-User-ID) dari konteks session.
 */
import { tenantHeaders, type Identity } from "./session";

// Port host API adalah 8080 (container internal: 8000) — lihat docker-compose.yml
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function apiFetch<T>(
  path: string,
  identity: Identity,
  init: RequestInit = {}
): Promise<T> {
  // JWT Bearer diutamakan bila pengguna sudah login (ala_token);
  // header identitas tetap dikirim sebagai fallback dev.
  const token =
    typeof window !== "undefined" ? localStorage.getItem("ala_token") : null;
  const res = await fetch(`${API_BASE_URL}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...tenantHeaders(identity),
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* abaikan body non-JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

const get = <T>(p: string, id: Identity) => apiFetch<T>(p, id);
const post = <T>(p: string, id: Identity, body?: unknown) =>
  apiFetch<T>(p, id, { method: "POST", body: body ? JSON.stringify(body) : undefined });

// --- Types ------------------------------------------------------------------

export interface SystemStatus {
  api: string;
  knowledge_ready: boolean;
  knowledge_score: number;
  ontology_nodes: number;
  laws_ingested: number;
}

export interface AlcdStatus extends SystemStatus {
  total_chunks: number;
  unresolved_gaps: number;
}

export interface OntologyNode {
  id: string;
  category: string;
  subcategory: string;
  priority: number;
  status: string;
  knowledge_score: number;
  laws_ingested: number;
}

export interface KnowledgeGap {
  id: string;
  question: string;
  answer_quality: number;
  gap_description: string;
  remediation_action: string;
}

export interface LegalArticle {
  law_name: string;
  article_number: string;
  title?: string;
  content?: string;
  relevance_score: number;
}

export interface CrimeSource {
  title: string;
  url: string;
  snippet?: string;
  published_date?: string;
}

export interface GeneratedOutput {
  filename?: string;
  language?: string;
  description?: string;
  code?: string;
  flowchart?: string;
  syntax_valid?: boolean;
}

export interface AnalysisResult {
  request_id: string;
  knowledge_ready: boolean;
  knowledge_score: number;
  legal_summary: string;
  legal_articles: LegalArticle[];
  cross_references: { from_article: string; to_article: string; relationship: string }[];
  crime_summary: string;
  crime_data: CrimeSource[];
  synthesis: Record<string, unknown>;
  generated_output: GeneratedOutput;
  errors: string[];
  requires_approval: boolean;
}

export interface AnalysisJob {
  request_id: string;
  kind: string;
  mode: string;
  query: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  stages_completed: string[];
  pipeline_stages: string[];
  stage_labels: Record<string, string>;
  started_at: number;
  finished_at: number | null;
  error: string | null;
  result?: AnalysisResult;
}

export interface ExecutionResult {
  request_id: string;
  status: string;
  exit_code?: number;
  timed_out?: boolean;
  guardrail_violations?: string[];
  stdout?: string;
  stderr?: string;
}

export interface Case {
  id: string;
  title: string;
  status: string;
  case_number?: string;
  crime_type?: string;
  priority?: string;
  created_at?: string;
}

export interface AuditLog {
  id: string;
  timestamp?: string;
  action: string;
  request_id: string;
  query_input: string;
  evidence_sha256_before?: string;
  evidence_sha256_after?: string;
}

export interface Institution {
  id: string;
  name: string;
  type: string;
  is_active: boolean;
  user_count: number;
}

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: string;
  tier_level: string;
  institution_id: string;
  is_active: boolean;
}

export interface Feature {
  id: string;
  name: string;
  slug: string;
  required_tier: string;
  is_ai_generated: boolean;
  ai_suggested_tier?: string;
  admin_approved_tier?: string;
  is_active: boolean;
}

// --- Endpoints ----------------------------------------------------------------

export const fetchSystemStatus = (id: Identity) =>
  get<SystemStatus>("/status", id);
export const fetchInstitutionOptions = (id: Identity) =>
  get<{ institutions: { id: string; name: string; type: string }[] }>(
    "/institutions",
    id
  );
export const fetchAlcdStatus = (id: Identity) =>
  get<AlcdStatus>("/alcd/status", id);
export const fetchOntology = (id: Identity) =>
  get<{ nodes: OntologyNode[] }>("/alcd/ontology", id);
export const fetchGaps = (id: Identity) =>
  get<{ gaps: KnowledgeGap[] }>("/alcd/gaps", id);
export const triggerAlcd = (id: Identity) =>
  post<{ request_id: string; status: string }>("/alcd/trigger", id);

export const startAnalysis = (
  id: Identity,
  query: string,
  mode: "full" | "legal" = "full",
  caseId?: string
) =>
  post<{ request_id: string; status: string }>("/analyze-trend", id, {
    query,
    mode,
    case_id: caseId || null,
  });
export const fetchAnalysis = (id: Identity, requestId: string) =>
  get<AnalysisJob>(`/analyze-trend/${requestId}`, id);
export const fetchActivity = (id: Identity) =>
  get<{ jobs: AnalysisJob[] }>("/activity", id);

export const approveWorkflow = (
  id: Identity,
  requestId: string,
  approved: boolean
) => post<ExecutionResult>("/approve-workflow", id, { request_id: requestId, approved });

export const fetchCases = (id: Identity) => get<{ cases: Case[] }>("/cases", id);
export const createCase = (
  id: Identity,
  body: { title: string; description?: string; case_number?: string; crime_type?: string; priority?: string }
) => post<{ id: string; status: string }>("/cases", id, body);

export const fetchAuditLogs = (id: Identity, limit = 50) =>
  get<{ logs: AuditLog[] }>(`/audit-logs?limit=${limit}`, id);

// --- Admin (super_admin saja) ---------------------------------------------------

export const fetchInstitutions = (id: Identity) =>
  get<{ institutions: Institution[] }>("/admin/institutions", id);
export const createInstitution = (id: Identity, name: string, type: string) =>
  post<{ id: string }>("/admin/institutions", id, { name, type });
export const fetchUsers = (id: Identity) =>
  get<{ users: AdminUser[] }>("/admin/users", id);
export const setUserTier = (id: Identity, userId: string, tier: string) =>
  post(`/admin/users/${userId}/tier`, id, { tier_level: tier });
export const fetchFeatures = (id: Identity) =>
  get<{ features: Feature[] }>("/admin/features", id);
export const overrideFeatureTier = (id: Identity, featureId: string, tier: string) =>
  post(`/admin/features/${featureId}/override-tier`, id, { tier_level: tier });
export const toggleFeature = (id: Identity, featureId: string) =>
  post(`/admin/features/${featureId}/toggle`, id);

// --- Auth (JWT lokal — POST /auth/login) -----------------------------------------

export interface LoginResult {
  token: string;
  token_type: string;
  expires_in_hours: number;
  user: {
    id: string; name: string; role: string; tier: string;
    institution_id: string;
  };
}

export async function loginApi(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || "Login gagal");
  }
  const data = (await res.json()) as LoginResult;
  localStorage.setItem("ala_token", data.token);
  return data;
}

export const logoutApi = () => localStorage.removeItem("ala_token");
export const isLoggedIn = () =>
  typeof window !== "undefined" && !!localStorage.getItem("ala_token");
