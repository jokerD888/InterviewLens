"use client";

import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2 } from "lucide-react";
import { fetcher, paths, type Summary } from "@/lib/api";

type Props = {
  company: string | null;
  position: string | null;
  period?: string;
};

export function SummaryView({ company, position, period = "all" }: Props) {
  const url = company && position ? paths.summary(company, position, period) : null;
  const { data, error, isLoading } = useSWR<Summary>(url, fetcher);

  if (!company || !position) {
    return (
      <Empty
        eyebrow="未选择"
        title="挑一家公司与一个岗位"
        hint="左栏点选公司，上方筛选岗位 — 对应的面经摘要会在此处展开。"
      />
    );
  }
  if (isLoading)
    return (
      <div className="flex items-center gap-2 p-6 font-mono text-xs uppercase tracking-widest text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> 调阅档案…
      </div>
    );
  if (error) {
    const msg = (error as Error).message;
    if (msg.includes("404"))
      return (
        <Empty
          eyebrow="尚无记录"
          title="该 公司 × 岗位 × 周期 暂无摘要"
          hint={`运行 il aggregate --company ${company} --position ${position} 生成`}
          code
        />
      );
    return <div className="p-6 font-mono text-sm text-bad">加载失败：{msg}</div>;
  }
  if (!data) return null;

  return (
    <article className="rise rise-2">
      <header className="mb-6 border-b border-ink/25 pb-4">
        <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-accent-ink">
          <span>Interview Archive</span>
          <span className="text-muted/50">/</span>
          <span className="text-muted">{data.period}</span>
        </div>
        <h1 className="font-display text-3xl font-black leading-tight tracking-masthead text-ink">
          {data.company}
          <span className="mx-2 font-normal text-rule">·</span>
          {data.position}
        </h1>
        <p className="mt-2 font-mono text-[11px] uppercase tracking-wider text-muted">
          基于 {data.sample_count} 道题
          {data.updated_at && (
            <span className="text-muted/70">
              {"  ·  "}更新于 {new Date(data.updated_at).toLocaleDateString("zh-CN")}
            </span>
          )}
        </p>
      </header>
      <div className="prose-il max-w-[68ch]">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.content_md}</ReactMarkdown>
      </div>
    </article>
  );
}

function Empty({
  eyebrow,
  title,
  hint,
  code,
}: {
  eyebrow: string;
  title: string;
  hint: string;
  code?: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-20 text-center">
      <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-accent">{eyebrow}</span>
      <p className="font-display text-xl font-semibold text-ink">{title}</p>
      <p className={code ? "rounded bg-sunk px-3 py-1.5 font-mono text-xs text-muted" : "max-w-sm text-sm text-muted"}>
        {hint}
      </p>
    </div>
  );
}
