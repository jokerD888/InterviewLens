"use client";

import { useState } from "react";
import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { Loader2, ChevronDown, ChevronRight } from "lucide-react";
import { fetcher, paths, type Summary, type Question } from "@/lib/api";

type Props = {
  company: string | null;
  position: string | null;
  period?: string;
};

export function SummaryView({ company, position, period = "all" }: Props) {
  const url = company && position ? paths.summary(company, position, period) : null;
  const { data, error, isLoading } = useSWR<Summary>(url, fetcher);

  // 完整题目清单
  const rawUrl = company && position ? paths.rawQuestions(company, position, period) : null;
  const [showRaw, setShowRaw] = useState(false);
  const { data: rawQuestions, isLoading: rawLoading } = useSWR<Question[]>(
    showRaw ? rawUrl : null,
    fetcher,
  );

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

      {/* LLM 摘要 */}
      <div className="prose-il max-w-[68ch]">
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{data.content_md}</ReactMarkdown>
      </div>

      {/* ── 完整题目清单（可折叠） ── */}
      <div className="mt-10 border-t border-ink/10 pt-6">
        <button
          onClick={() => setShowRaw(!showRaw)}
          className="group flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-muted/50 hover:text-muted transition-colors"
        >
          {showRaw ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          📋 完整题目清单
          {rawQuestions && (
            <span className="text-muted/30">（{rawQuestions.length} 道）</span>
          )}
        </button>

        {showRaw && (
          rawLoading ? (
            <div className="flex items-center gap-2 py-8 font-mono text-xs text-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载题目…
            </div>
          ) : rawQuestions && rawQuestions.length > 0 ? (
            <RawQuestionList questions={rawQuestions} />
          ) : (
            <p className="py-4 font-mono text-xs text-muted">暂无原始题目数据。</p>
          )
        )}
      </div>
    </article>
  );
}

/** 按 category 分组 + 逐条罗列 */
function RawQuestionList({ questions }: { questions: Question[] }) {
  const grouped: Record<string, Question[]> = {};
  for (const q of questions) {
    const cat = q.category || "未分类";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(q);
  }

  return (
    <div className="mt-4 space-y-6">
      {Object.entries(grouped).map(([cat, qs]) => (
        <section key={cat}>
          <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted/60 mb-3">
            {cat} <span className="text-muted/30">· {qs.length}</span>
          </h3>
          <ol className="space-y-3 list-decimal list-inside">
            {qs.map((q) => (
              <li key={q.id} className="pl-1">
                <p className="inline text-sm text-ink/90 leading-relaxed">{q.content}</p>
                {q.answer_brief && (
                  <p className="mt-1 ml-0 pl-5 border-l-2 border-accent/20 text-xs text-muted/70 leading-relaxed">
                    {q.answer_brief}
                  </p>
                )}
                {q.source_url && (
                  <a
                    href={q.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-2 font-mono text-[10px] text-muted/30 hover:text-accent-ink underline underline-offset-2"
                  >
                    来源 →
                  </a>
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
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
