"use client";

import useSWR from "swr";
import { Activity, AlertCircle, Cpu } from "lucide-react";
import { fetcher, type Health, type Jobs } from "@/lib/api";

export default function AdminPage() {
  const { data: health } = useSWR<Health>("/admin/health", fetcher, { refreshInterval: 5000 });
  const { data: jobs } = useSWR<Jobs>("/admin/jobs", fetcher, { refreshInterval: 5000 });
  const { data: metrics } = useSWR<MetricsBody>("/admin/metrics", fetcher, { refreshInterval: 5000 });

  return (
    <div className="mx-auto max-w-screen-xl space-y-4 p-4">
      <Section title="健康状态" icon={<Activity className="h-4 w-4" />}>
        {!health ? (
          <Skel />
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="overall" value={health.status} ok={health.status === "ok"} />
            <Stat label="postgres" value={String(health.pg)} ok={health.pg} />
            <Stat label="pgvector" value={String(health.pgvector)} ok={health.pgvector} />
            <Stat label="redis" value={String(health.redis)} ok={health.redis} />
          </div>
        )}
      </Section>

      <Section title="任务队列" icon={<Cpu className="h-4 w-4" />}>
        {!jobs ? (
          <Skel />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Card title="队列长度">
              {Object.keys(jobs.queues).length === 0 ? (
                <p className="text-xs text-muted">空</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {Object.entries(jobs.queues).map(([k, v]) => (
                    <li key={k} className="flex justify-between">
                      <span className="text-muted">{k}</span>
                      <span>{v}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="活跃 worker">
              {jobs.workers.length === 0 ? (
                <p className="text-xs text-muted">无</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {jobs.workers.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="死信队列" badge={Object.keys(jobs.dlq).length > 0 ? "warn" : undefined}>
              {Object.keys(jobs.dlq).length === 0 ? (
                <p className="text-xs text-muted">空</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {Object.entries(jobs.dlq).map(([k, v]) => (
                    <li key={k} className="flex items-center justify-between">
                      <span className="text-muted">{k}</span>
                      <span className="text-warn">{v}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        )}
      </Section>

      <Section title="LLM 指标" icon={<AlertCircle className="h-4 w-4" />}>
        {!metrics ? (
          <Skel />
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="cache hit rate" value={`${(metrics.cache.hit_rate * 100).toFixed(1)}%`} />
            <Stat label="hits / misses" value={`${metrics.cache.hits} / ${metrics.cache.misses}`} />
            <Stat label="total tokens" value={metrics.tokens.total.toLocaleString()} />
            <Stat label="cost" value={`¥${metrics.tokens.estimated_cost_cny.toFixed(4)}`} />
          </div>
        )}
        {metrics?.node_runs && Object.keys(metrics.node_runs).length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs uppercase tracking-wider text-muted">节点延迟</p>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="py-1 text-left">node</th>
                  <th className="py-1 text-right">runs</th>
                  <th className="py-1 text-right">avg ms</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(metrics.node_runs).map((k) => (
                  <tr key={k} className="border-t border-border">
                    <td className="py-1">{k}</td>
                    <td className="py-1 text-right">{metrics.node_runs[k]}</td>
                    <td className="py-1 text-right">{(metrics.node_avg_ms[k] ?? 0).toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

type MetricsBody = {
  cache: { hits: number; misses: number; hit_rate: number };
  tokens: { prompt: number; completion: number; total: number; estimated_cost_cny: number };
  node_runs: Record<string, number>;
  node_avg_ms: Record<string, number>;
};

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2 rounded-lg border border-border bg-panel/40 p-4">
      <h2 className="flex items-center gap-2 text-sm font-medium">
        {icon}
        {title}
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
    <div className="rounded border border-border bg-bg p-3">
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs uppercase tracking-wider text-muted">{title}</p>
        {badge === "warn" && <span className="h-1.5 w-1.5 rounded-full bg-warn" />}
      </div>
      {children}
    </div>
  );
}

function Stat({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok?: boolean;
}) {
  return (
    <div className="rounded border border-border bg-bg p-3">
      <p className="text-xs uppercase tracking-wider text-muted">{label}</p>
      <p className={`text-sm ${ok === false ? "text-bad" : ok ? "text-good" : "text-ink"}`}>{value}</p>
    </div>
  );
}

function Skel() {
  return <div className="h-12 animate-pulse rounded bg-panel/60" />;
}
