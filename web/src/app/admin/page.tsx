"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Activity, Boxes, Gauge, Inbox, Trash2, Loader2, Send } from "lucide-react";
import {
  fetcher,
  mutate as apiMutate,
  paths,
  type Health,
  type Jobs,
  type DlqList,
} from "@/lib/api";
import { cn } from "@/lib/cn";

type MetricsBody = {
  cache: { hits: number; misses: number; hit_rate: number };
  tokens: { prompt: number; completion: number; total: number; estimated_cost_cny: number };
  node_runs: Record<string, number>;
  node_avg_ms: Record<string, number>;
};

export default function AdminPage() {
  const { data: health } = useSWR<Health>(paths.health(), fetcher, { refreshInterval: 5000 });
  const { data: jobs } = useSWR<Jobs>(paths.jobs(), fetcher, { refreshInterval: 5000 });
  const { data: metrics } = useSWR<MetricsBody>(paths.metrics(), fetcher, { refreshInterval: 5000 });

  return (
    <div className="mx-auto max-w-screen-xl space-y-5 px-6 py-6">
      <div className="rise rise-1">
        <p className="font-mono text-[10px] uppercase tracking-[0.3em] text-accent">控制台</p>
        <h1 className="font-display text-2xl font-black tracking-masthead text-ink">机房 · Operations</h1>
      </div>

      <div className="rise rise-2 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Section title="健康状态" icon={<Activity className="h-3.5 w-3.5" />} index="01">
          {!health ? (
            <Skel />
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="overall" value={health.status} ok={health.status === "ok"} />
              <Stat label="postgres" value={health.pg ? "up" : "down"} ok={health.pg} />
              <Stat label="pgvector" value={health.pgvector ? "up" : "down"} ok={health.pgvector} />
              <Stat label="redis" value={health.redis ? "up" : "down"} ok={health.redis} />
            </div>
          )}
        </Section>

        <Section title="手动入库" icon={<Send className="h-3.5 w-3.5" />} index="02">
          <IngestForm />
        </Section>
      </div>

      <Section title="任务队列" icon={<Boxes className="h-3.5 w-3.5" />} index="03" className="rise rise-3">
        {!jobs ? (
          <Skel />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Card title="队列长度">
                {Object.keys(jobs.queues).length === 0 ? (
                  <Empty>空</Empty>
                ) : (
                  <KvList rows={Object.entries(jobs.queues)} />
                )}
              </Card>
              <Card title="活跃 worker">
                {jobs.workers.length === 0 ? (
                  <Empty>无在线 worker</Empty>
                ) : (
                  <ul className="space-y-1 font-mono text-xs text-ink">
                    {jobs.workers.map((w) => (
                      <li key={w} className="flex items-center gap-2">
                        <span className="h-1.5 w-1.5 rounded-full bg-good" />
                        {w}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
            <DlqPanel dlq={jobs.dlq} />
          </div>
        )}
      </Section>

      <Section title="LLM 指标" icon={<Gauge className="h-3.5 w-3.5" />} index="04">
        {!metrics ? (
          <Skel />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="cache hit rate" value={`${(metrics.cache.hit_rate * 100).toFixed(1)}%`} />
              <Stat label="hits / misses" value={`${metrics.cache.hits} / ${metrics.cache.misses}`} />
              <Stat label="total tokens" value={metrics.tokens.total.toLocaleString()} />
              <Stat label="cost" value={`¥${metrics.tokens.estimated_cost_cny.toFixed(4)}`} />
            </div>
            {metrics.node_runs && Object.keys(metrics.node_runs).length > 0 && (
              <div className="mt-4">
                <p className="mb-1 font-mono text-[10px] uppercase tracking-widest text-muted">节点延迟</p>
                <table className="w-full font-mono text-xs">
                  <thead className="text-[10px] uppercase tracking-wider text-muted">
                    <tr className="border-b border-ink/25">
                      <th className="py-1 text-left">node</th>
                      <th className="py-1 text-right">runs</th>
                      <th className="py-1 text-right">avg ms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(metrics.node_runs).map((k) => (
                      <tr key={k} className="border-b border-border">
                        <td className="py-1 text-ink">{k}</td>
                        <td className="py-1 text-right tabular-nums">{metrics.node_runs[k]}</td>
                        <td className="py-1 text-right tabular-nums">{(metrics.node_avg_ms[k] ?? 0).toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Section>
    </div>
  );
}

/* ── Manual ingest (POST /admin/ingest) ─────────────────────────────── */
function IngestForm() {
  const [url, setUrl] = useState("");
  const [skipNormalize, setSkipNormalize] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const u = url.trim();
    if (!u) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await apiMutate.ingest(u, skipNormalize);
      if (r.ok) {
        setResult({ ok: true, msg: `已入队 · task ${r.task_id?.slice(0, 8)}…` });
        setUrl("");
      } else {
        setResult({ ok: false, msg: r.error ?? "入队失败" });
      }
    } catch (err) {
      setResult({ ok: false, msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2.5">
      <div className="flex items-center gap-2 border-b border-ink/40 px-1 py-1 focus-within:border-accent">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.nowcoder.com/discuss/123…"
          className="flex-1 bg-transparent font-mono text-xs text-ink outline-none placeholder:text-muted/50"
        />
        <button
          type="submit"
          disabled={busy || !url.trim()}
          className="inline-flex items-center gap-1 rounded-sm bg-ink px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-bg transition hover:bg-accent disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
          入队
        </button>
      </div>
      <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-muted">
        <input
          type="checkbox"
          checked={skipNormalize}
          onChange={(e) => setSkipNormalize(e.target.checked)}
          className="accent-accent"
        />
        跳过归一化 (skip_normalize)
      </label>
      {result && (
        <p className={cn("font-mono text-[11px]", result.ok ? "text-good" : "text-bad")}>{result.msg}</p>
      )}
    </form>
  );
}

/* ── Dead-letter queue inspect + clear (GET/DELETE /admin/dlq/{name}) ── */
function DlqPanel({ dlq }: { dlq: Record<string, number> }) {
  const entries = Object.entries(dlq);
  return (
    <Card title="死信队列" badge={entries.length > 0 ? "warn" : undefined}>
      {entries.length === 0 ? (
        <Empty>空 · 无失败任务</Empty>
      ) : (
        <ul className="divide-y divide-border">
          {entries.map(([key, n]) => (
            // key is the full redis key "il:dlq:<task_name>"; endpoints want the bare name.
            <DlqRow key={key} taskName={key.replace(/^il:dlq:/, "")} count={n} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function DlqRow({ taskName, count }: { taskName: string; count: number }) {
  const { mutate: globalMutate } = useSWRConfig();
  const [open, setOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const { data, isLoading } = useSWR<DlqList>(open ? paths.dlq(taskName) : null, fetcher);

  async function clear() {
    setClearing(true);
    try {
      await apiMutate.clearDlq(taskName);
      setOpen(false);
      globalMutate(paths.jobs()); // refresh the counts panel
    } finally {
      setClearing(false);
    }
  }

  return (
    <li className="py-1.5">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 font-mono text-xs text-ink transition hover:text-accent-ink"
        >
          <Inbox className="h-3 w-3" />
          {taskName}
          <span className="tabular-nums text-warn">{count}</span>
        </button>
        <button
          onClick={clear}
          disabled={clearing}
          className="inline-flex items-center gap-1 rounded-sm border border-bad/50 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-bad transition hover:bg-bad hover:text-bg disabled:opacity-40"
        >
          {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
          清空
        </button>
      </div>
      {open && (
        <div className="mt-1.5 max-h-52 overflow-y-auto rounded-sm bg-sunk/70 p-2">
          {isLoading ? (
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted">读取…</p>
          ) : data && data.items.length > 0 ? (
            <ul className="space-y-1.5">
              {data.items.map((item, i) => (
                <li key={i} className="border-l-2 border-bad/40 pl-2 font-mono text-[10px] leading-relaxed text-muted">
                  <pre className="whitespace-pre-wrap break-all">{JSON.stringify(item, null, 0)}</pre>
                </li>
              ))}
            </ul>
          ) : (
            <p className="font-mono text-[10px] text-muted">无明细</p>
          )}
        </div>
      )}
    </li>
  );
}

/* ── Presentational primitives ──────────────────────────────────────── */
function Section({
  title,
  icon,
  index,
  className,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  index: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("space-y-3 border border-border bg-panel/40 p-5 shadow-card", className)}>
      <h2 className="flex items-center gap-2 border-b border-ink/20 pb-2">
        <span className="font-mono text-[10px] tabular-nums text-accent">{index}</span>
        <span className="text-accent">{icon}</span>
        <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink">{title}</span>
      </h2>
      {children}
    </section>
  );
}

function Card({
  title,
  children,
  badge,
}: {
  title: string;
  children: React.ReactNode;
  badge?: "warn";
}) {
  return (
    <div className="border border-border bg-bg p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="font-mono text-[10px] uppercase tracking-widest text-muted">{title}</p>
        {badge === "warn" && <span className="h-1.5 w-1.5 rounded-full bg-warn" />}
      </div>
      {children}
    </div>
  );
}

function KvList({ rows }: { rows: [string, number][] }) {
  return (
    <ul className="space-y-1 font-mono text-xs">
      {rows.map(([k, v]) => (
        <li key={k} className="flex justify-between">
          <span className="text-muted">{k}</span>
          <span className="tabular-nums text-ink">{v}</span>
        </li>
      ))}
    </ul>
  );
}

function Stat({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="border border-border bg-bg p-3">
      <p className="font-mono text-[10px] uppercase tracking-widest text-muted">{label}</p>
      <p
        className={cn(
          "mt-0.5 font-mono text-sm tabular-nums",
          ok === false ? "text-bad" : ok ? "text-good" : "text-ink",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="font-mono text-[10px] uppercase tracking-wider text-muted/70">{children}</p>;
}

function Skel() {
  return <div className="h-12 animate-pulse rounded bg-sunk/70" />;
}
