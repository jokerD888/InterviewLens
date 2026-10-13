"use client";

import { useState } from "react";
import { ExternalLink, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";
import { AnswerBlock } from "@/components/answer-block";
import type { PostFeedItem } from "@/lib/api";
import { fetcher, type FeedQuestion } from "@/lib/api";
import useSWRInfinite from "swr/infinite";

type Props = {
  post: PostFeedItem;
};

export function FeedCard({ post }: Props) {
  const [open, setOpen] = useState(false);
  const { data, error, size, setSize, isValidating } = useSWRInfinite<FeedQuestion[]>(
    (page, previous) => !open || (previous && previous.length < 50)
      ? null : `/posts/${post.id}/questions?limit=50&offset=${page * 50}`,
    fetcher,
  );
  const questions = data?.flat() ?? [];
  const when = post.posted_at ? fmtDate(post.posted_at) : null;

  return (
    <article className="border-b border-border/60 bg-panel/30 transition hover:bg-panel/60">
      <div className="px-4 py-3">
        {/* Meta row */}
        <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] uppercase tracking-wider text-muted">
          {post.companies.slice(0, 3).map((c) => (
            <span key={c} className="rounded-sm bg-ink/10 px-1.5 py-0.5 text-ink/80">
              {c}
            </span>
          ))}
          {!post.position_profiles?.length && post.positions.slice(0, 3).map((p) => (
            <span key={p} className="text-ink/60">
              {p}
            </span>
          ))}
          {when && (
            <span className="ml-auto tabular-nums text-muted/70">{when}</span>
          )}
        </div>

        {/* Round types */}
        {post.position_profiles?.map((profile, index) => (
          <div key={index} className="mb-2 text-xs text-muted">
            <span className="text-ink">{profile.category ?? (profile.status === "out_of_scope" ? "非研发岗位" : "岗位未明确")}</span>
            {profile.specializations.length > 0 && <span className="ml-2">方向：{profile.specializations.join(" / ")}</span>}
            {profile.domains.length > 0 && <span className="ml-2">业务：{profile.domains.join(" / ")}</span>}
          </div>
        ))}
        {post.round_types.length > 0 && (
          <div className="mb-1 flex flex-wrap gap-1 text-[11px] text-muted">
            {post.round_types.map((r) => (
              <span
                key={r}
                className="rounded-full border border-border/70 px-2 py-0.5 font-mono text-[10px]"
              >
                {r}
              </span>
            ))}
            <span className="font-mono text-[10px] text-muted/60">
              {post.question_count} 题
            </span>
          </div>
        )}

        {/* Title / excerpt */}
        {post.title && (
          <p className="font-serif text-lg leading-snug font-medium text-ink">
            {post.title}
          </p>
        )}
        {post.excerpt && (
          <p className={cn("text-[15px] leading-relaxed text-muted", post.title && "mt-0.5")}>
            {post.excerpt}
          </p>
        )}

        {/* Expand toggle */}
        <button
          onClick={() => setOpen((v) => !v)}
          className="mt-2 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-muted transition hover:text-accent"
        >
          <ChevronDown className={cn("h-3 w-3 transition", open && "rotate-180")} />
          {open ? "收起详情" : "展开详情"}
        </button>

        {/* Expanded body */}
        {open && (
          <div className="mt-4 space-y-5 border-t border-border/60 pt-4">
            {post.position_profiles?.map((profile, index) => (
              <section key={index} className="text-sm text-muted">
                <h4 className="mb-2 text-ink">岗位信息</h4>
                {profile.skills.length > 0 && <p>技术栈：{profile.skills.join(" / ")}</p>}

              </section>
            ))}
            {error && <p role="alert" className="text-sm text-muted">题目加载失败，请收起后重新展开。</p>}
            {!data && !error && <p className="text-sm text-muted">正在加载题目…</p>}
            {questions.length > 0 && (
              <section>
                <h4 className="mb-3 font-mono text-[10px] uppercase tracking-widest text-muted">
                  ¶ 面试问题 ({post.question_count})
                </h4>
                <ol className="space-y-4">
                  {questions.map((q) => (
                    <li key={q.id} className="border-l-2 border-border pl-3">
                      <div className="flex items-center gap-2 mb-1">
                        {q.round_type && (
                          <span className="font-mono text-[10px] uppercase tracking-wide text-muted">
                            {q.round_type}
                          </span>
                        )}
                        {q.round_no != null && (
                          <span className="font-mono text-[10px] text-muted/60">
                            Q{q.round_no}
                          </span>
                        )}
                      </div>
                      <p className="font-serif text-[16px] leading-relaxed text-ink">
                        {q.content}
                      </p>
                      {q.answer_brief && (
                        <details className="mt-1.5 text-[14px] text-muted">
                          <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-widest text-muted hover:text-accent-ink">
                            ¶ 原帖答案要点
                          </summary>
                          <p className="mt-1 border-l border-border pl-3">{q.answer_brief}</p>
                        </details>
                      )}
                      <AnswerBlock answer={q.answer_ai} />
                    </li>
                  ))}
                </ol>
                {questions.length < post.question_count && !error && (
                  <button disabled={isValidating} onClick={() => setSize(size + 1)} className="mt-3 text-sm text-muted hover:text-accent">
                    {isValidating ? "正在加载…" : "加载更多题目"}
                  </button>
                )}
              </section>
            )}

            <a
              href={post.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-muted transition hover:text-accent"
            >
              <ExternalLink className="h-3 w-3" />
              牛客原帖
            </a>
          </div>
        )}
      </div>
    </article>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 86400000 && d.getDate() === now.getDate()) return "今天";
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.getDate() === yesterday.getDate() && d.getMonth() === yesterday.getMonth() && d.getFullYear() === yesterday.getFullYear())
    return "昨天";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}
