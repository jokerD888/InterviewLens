"use client";

import { ExternalLink, Sparkles } from "lucide-react";
import { type Question } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  q: Question;
  highlight?: string;
};

export function QuestionCard({ q, highlight }: Props) {
  const sim = q.similarity != null ? Math.round(q.similarity * 100) : null;
  return (
    <div className="rounded-lg border border-border bg-panel p-3 transition hover:border-accent/40">
      <div className="mb-1.5 flex items-center gap-2 text-xs text-muted">
        {q.category && (
          <span className="rounded bg-bg px-1.5 py-0.5 text-ink">{q.category}</span>
        )}
        {q.round_type && <span>{q.round_type}</span>}
        {q.quality_score != null && (
          <span className={cn(q.quality_score >= 70 ? "text-good" : q.quality_score >= 40 ? "text-warn" : "text-muted")}>
            分 {q.quality_score}
          </span>
        )}
        {sim != null && (
          <span className="ml-auto inline-flex items-center gap-0.5 text-accent">
            <Sparkles className="h-3 w-3" /> {sim}%
          </span>
        )}
      </div>
      <p className="text-sm leading-6">
        <Highlight text={q.content} term={highlight} />
      </p>
      {q.answer_brief && (
        <details className="mt-2 text-sm text-muted">
          <summary className="cursor-pointer text-xs uppercase tracking-wide hover:text-ink">
            原帖答案要点
          </summary>
          <p className="mt-1 leading-6">{q.answer_brief}</p>
        </details>
      )}
      {q.source_url && (
        <a
          href={q.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          <ExternalLink className="h-3 w-3" /> 原帖
        </a>
      )}
    </div>
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
          <mark key={i} className="rounded bg-accent/30 text-ink">
            {p}
          </mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
