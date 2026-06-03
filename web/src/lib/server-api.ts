// Server-side fetcher used in RSC. Goes direct to FastAPI (no rewrites needed
// because it runs in Node, not the browser). Falls back to localhost if the
// env var is not set so the dev experience is one-config.
const SERVER_API_BASE =
  process.env.API_BASE ?? process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function ssrFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${SERVER_API_BASE}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!resp.ok) {
    throw new Error(`SSR HTTP ${resp.status} on ${path}`);
  }
  return resp.json() as Promise<T>;
}
