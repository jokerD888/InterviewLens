"use client";

import { useState } from "react";
import useSWR from "swr";
import { ExternalLink, Sparkles, ChevronDown, Loader2 } from "lucide-react";
import { fetcher, paths, type Question, type PostBrief } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AnswerBlock } from "@/components/answer-block";

type Props = {
  q: Question;
  highlight?: string;
  expandAll?: boolean;
};

export function QuestionCard({ q, highlight, expandAll }: Props) {
  const sim = q.similarity != null ? Math.round(q.similarity * 100) : null;
  const [open, setOpen] = useState(false);

  return (
    <article className="group border-l-2 border-border bg-panel/40 py-3 pl-4 pr-3 transition hover:border-l-accent hover:bg-panel">
      <div className="mb-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 font-mono text-[10px] uppercase tracking-wider text-muted">
        {q.category && (
          <span className="rounded-sm bg-ink px-1.5 py-0.5 text-bg">{q.category}</span>
        )}
        {q.round_type && <span>{q.round_type}</span>}
        {q.quality_score != null && (
          <span
            className={cn(
              "tabular-nums",
              q.quality_score >= 70 ? "text-good" : q.quality_score >= 40 ? "text-warn" : "text-muted",
            )}
          >
            分 {q.quality_score}
          </span>
        )}
        {sim != null && (
          <span className="ml-auto inline-flex items-center gap-1 text-accent-ink">
            <Sparkles className="h-3 w-3" /> {sim}% 相似
          </span>
        )}
      </div>

      <p className="font-serif text-[17px] leading-relaxed text-ink">
        <Highlight text={q.content} term={highlight} />
      </p>

      {q.answer_brief && (
        <details className="mt-2 text-[15px] leading-relaxed text-muted">
          <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-widest text-muted hover:text-accent-ink">
            ¶ 原帖答案要点
          </summary>
          <p className="mt-1.5 border-l border-border pl-3">{q.answer_brief}</p>
        </details>
      )}

      <AnswerBlock answer={q.answer_ai} expandAll={expandAll} />

      <div className="mt-2.5 flex items-center gap-4">
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-muted transition hover:text-accent-ink"
        >
          <ChevronDown className={cn("h-3 w-3 transition", open && "rotate-180")} />
          帖子出处
        </button>
        {q.source_url && (
          <a
            href={q.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-accent-ink hover:underline"
          >
            <ExternalLink className="h-3 w-3" /> 原帖
          </a>
        )}
      </div>

      {open && <PostDetail postId={q.post_id} />}
    </article>
  );
}

/** Lazily resolves GET /posts/{id} when the card's "帖子出处" is expanded. */
function PostDetail({ postId }: { postId: number }) {
  const { data, error, isLoading } = useSWR<PostBrief>(paths.post(postId), fetcher);

  if (isLoading)
    return (
      <div className="mt-2 flex items-center gap-2 border-t border-border pt-2 font-mono text-[10px] uppercase tracking-widest text-muted">
        <Loader2 className="h-3 w-3 animate-spin" /> 读取帖子…
      </div>
    );
  if (error) return <p className="mt-2 border-t border-border pt-2 font-mono text-[10px] text-bad">出处加载失败</p>;
  if (!data) return null;

  return (
    <div className="mt-2.5 space-y-1.5 border-t border-border pt-2.5 text-sm">
      {data.title && <p className="font-display text-[15px] font-semibold text-ink">{data.title}</p>}
      <div className="flex flex-wrap gap-1.5">
        {data.companies.map((c) => (
          <Tag key={`c-${c}`}>{c}</Tag>
        ))}
        {data.positions.map((p) => (
          <Tag key={`p-${p}`} accent>
            {p}
          </Tag>
        ))}
      </div>
      <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-muted">
        {data.posted_at && <span>发布于 {new Date(data.posted_at).toLocaleDateString("zh-CN")}</span>}
        {data.quality_score != null && <span className="tabular-nums">帖子分 {data.quality_score}</span>}
      </div>
    </div>
  );
}

function Tag({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-sm border px-1.5 py-0.5 font-mono text-[10px]",
        accent ? "border-accent/50 text-accent-ink" : "border-border text-muted",
      )}
    >
      {children}
    </span>
  );
}

function Highlight({ text, term }: { text: string; term?: string }) {
  if (!term) return <>{text}</>;
  const safe = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(${safe})`, "gi");
  const parts = text.split(re);
  return (
    <>
      {parts.map((p, i) =>
        re.test(p) ? (
          <mark key={i} className="rounded-sm bg-accent/25 px-0.5 text-ink">
            {p}
          </mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
