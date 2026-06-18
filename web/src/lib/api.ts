// API layer. Browser calls go through Next.js rewrites at /api/* → FastAPI :8000
// (avoids CORS, works behind a reverse proxy with no client env-var gymnastics).
//
// URL construction lives HERE and nowhere else. Components import `paths.*`
// builders and pass them straight to SWR as cache keys + to `fetcher`. This
// keeps every request string in one file, so the contract with the backend
// can't silently drift across components.

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
  answer_ai: string | null;
  quality_score: number | null;
  source_url: string | null;
  similarity: number | null;
};

export type PostBrief = {
  id: number;
  title: string | null;
  source_url: string;
  posted_at: string | null;
  quality_score: number | null;
  companies: string[];
  positions: string[];
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

export type DlqList = {
  task_name: string;
  count: number;
  items: Record<string, unknown>[];
};

// Bridge types
export type BridgeGeneratedAnswer = {
  question_id: number;
  content: string;
  category: string | null;
  generated_answer: string | null;
  importance_score: number;
  error: string | null;
};

export type BridgeGenerateResponse = {
  answers: BridgeGeneratedAnswer[];
};

export type BridgeExportRequest = {
  cards: {
    question: string;
    answer: string;
    importance_score: number;
    source_url?: string | null;
  }[];
};

export type BridgeExportResponse = {
  imported: number;
  skipped: number;
  skipped_reasons: string[];
};

const API_PREFIX = "/api";

function qs(params: Record<string, string | number | null | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

/**
 * Path builders — the single source of truth for every backend route the UI
 * touches. Each returns a path beginning with "/", suitable as an SWR key.
 */
export const paths = {
  companies: () => `/companies${qs({ with_counts: "true", limit: 200 })}`,
  companyPositions: (id: number) => `/companies/${id}/positions`,
  positions: () => `/positions${qs({ with_counts: "true", limit: 200 })}`,

  search: (p: {
    q: string;
    company?: string | null;
    position?: string | null;
    minQuality?: number;
    limit?: number;
  }) =>
    `/posts/search${qs({
      q: p.q,
      company: p.company,
      position: p.position,
      min_quality: p.minQuality && p.minQuality > 0 ? p.minQuality : undefined,
      limit: p.limit ?? 20,
    })}`,

  post: (id: number) => `/posts/${id}`,

  summaries: (p?: { company?: string; position?: string; period?: string; limit?: number }) =>
    `/summaries${qs({
      company: p?.company,
      position: p?.position,
      period: p?.period,
      limit: p?.limit,
    })}`,
  summary: (company: string, position: string, period = "all") =>
    `/summaries/${encodeURIComponent(company)}/${encodeURIComponent(position)}${qs({ period })}`,

  rawQuestions: (company: string, position: string, period = "all") =>
    `/summaries/${encodeURIComponent(company)}/${encodeURIComponent(position)}/questions${qs({ period })}`,

  health: () => `/admin/health`,
  jobs: () => `/admin/jobs`,
  metrics: () => `/admin/metrics`,
  dlq: (taskName: string, limit = 50) => `/admin/dlq/${encodeURIComponent(taskName)}${qs({ limit })}`,
};

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_PREFIX}${path}`, { cache: "no-store", ...init });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} on ${path}`);
  return resp.json() as Promise<T>;
}

/** SWR fetcher — pass any `paths.*` result as the key. */
export const fetcher = <T>(path: string) => http<T>(path);

/** Mutations (not cached). Used by the admin console. */
export const mutate = {
  ingest: (url: string, skipNormalize = false) =>
    http<{ ok: boolean; task_id?: string; url?: string; error?: string }>(`/admin/ingest`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url, skip_normalize: skipNormalize }),
    }),
  clearDlq: (taskName: string) =>
    http<{ cleared: number; task_name: string }>(`/admin/dlq/${encodeURIComponent(taskName)}`, {
      method: "DELETE",
    }),
};

/** Bridge API — export questions to daily-interview-prep. */
export const bridge = {
  generateAnswers: (questionIds: number[]) =>
    http<BridgeGenerateResponse>(`/bridge/generate-answers`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question_ids: questionIds }),
    }),
  export: (cards: BridgeExportRequest["cards"]) =>
    http<BridgeExportResponse>(`/bridge/export`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ cards }),
    }),
};
