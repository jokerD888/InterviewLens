// API client. Goes through Next.js rewrites at /api/* → FastAPI :8000
// This avoids CORS in production and lets the same code work behind a reverse
// proxy without env-var gymnastics on the client.

export type Company = {
  id: number;
  canonical: string;
  industry: string | null;
  post_count: number | null;
};

export type Position = {
  id: number;
  canonical: string;
  category: string | null;
  post_count: number | null;
};

export type CompanyPositionStat = {
  company_id: number;
  company_name: string;
  position_id: number;
  position_name: string;
  post_count: number;
  avg_quality: number | null;
  latest_posted_at: string | null;
};

export type Question = {
  id: number;
  post_id: number;
  round_no: number | null;
  round_type: string | null;
  content: string;
  category: string | null;
  answer_brief: string | null;
  quality_score: number | null;
  source_url: string | null;
  similarity: number | null;
};

export type Summary = {
  id: number;
  company: string;
  position: string;
  period: string;
  sample_count: number;
  content_md: string;
  updated_at: string | null;
};

export type Health = {
  status: string;
  pg: boolean;
  redis: boolean;
  pgvector: boolean;
};

export type Jobs = {
  queues: Record<string, number>;
  dlq: Record<string, number>;
  workers: string[];
};

const API_PREFIX = "/api";

async function http<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_PREFIX}${path}`, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} on ${path}`);
  }
  return resp.json() as Promise<T>;
}

export const fetcher = <T>(path: string) => http<T>(path);

export const api = {
  companies: () => http<Company[]>(`/companies?with_counts=true&limit=200`),
  companyPositions: (id: number) => http<CompanyPositionStat[]>(`/companies/${id}/positions`),
  positions: () => http<Position[]>(`/positions?with_counts=true&limit=200`),
  search: (params: {
    q: string;
    company?: string | null;
    position?: string | null;
    minQuality?: number;
    limit?: number;
  }) => {
    const usp = new URLSearchParams({ q: params.q });
    if (params.company) usp.set("company", params.company);
    if (params.position) usp.set("position", params.position);
    if (params.minQuality && params.minQuality > 0)
      usp.set("min_quality", String(params.minQuality));
    usp.set("limit", String(params.limit ?? 20));
    return http<Question[]>(`/posts/search?${usp.toString()}`);
  },
  summaries: (params?: { company?: string; position?: string; period?: string }) => {
    const usp = new URLSearchParams();
    if (params?.company) usp.set("company", params.company);
    if (params?.position) usp.set("position", params.position);
    if (params?.period) usp.set("period", params.period);
    const q = usp.toString();
    return http<Summary[]>(`/summaries${q ? "?" + q : ""}`);
  },
  summary: (company: string, position: string, period: string = "all") =>
    http<Summary>(
      `/summaries/${encodeURIComponent(company)}/${encodeURIComponent(position)}?period=${encodeURIComponent(period)}`,
    ),
  health: () => http<Health>(`/admin/health`),
  jobs: () => http<Jobs>(`/admin/jobs`),
};
