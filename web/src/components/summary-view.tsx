"use client";

import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2 } from "lucide-react";
import { fetcher, type Summary } from "@/lib/api";

type Props = {
  company: string | null;
  position: string | null;
  period?: string;
};

export function SummaryView({ company, position, period = "all" }: Props) {
  const url =
    company && position
      ? `/summaries/${encodeURIComponent(company)}/${encodeURIComponent(position)}?period=${encodeURIComponent(period)}`
      : null;
  const { data, error, isLoading } = useSWR<Summary>(url, fetcher);

  if (!company || !position) {
    return (
      <Empty
        title="选择公司 + 岗位查看摘要"
        hint="左侧公司列表 + 顶部岗位筛选选好后会自动加载"
      />
    );
  }
  if (isLoading)
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载摘要…
      </div>
    );
  if (error) {
    const msg = (error as Error).message;
    if (msg.includes("404"))
      return (
        <Empty
          title="该 (公司 × 岗位 × 周期) 暂无摘要"
          hint={`运行 \`uv run il aggregate --company ${company} --position ${position}\` 生成`}
        />
      );
    return <div className="p-4 text-sm text-bad">加载失败：{msg}</div>;
  }
  if (!data) return null;

  return (
    <article>
      <header className="mb-4">
        <h1 className="text-lg font-medium">
          {data.company} · {data.position} <span className="text-muted">· {data.period}</span>
        </h1>
        <p className="text-xs text-muted">
          基于 {data.sample_count} 道题
          {data.updated_at && ` · 更新于 ${new Date(data.updated_at).toLocaleString("zh-CN")}`}
        </p>
      </header>
      <div className="prose-il">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.content_md}</ReactMarkdown>
      </div>
    </article>
  );
}

function Empty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-12 text-center">
      <p className="text-sm text-ink">{title}</p>
      <p className="text-xs text-muted">{hint}</p>
    </div>
  );
}
