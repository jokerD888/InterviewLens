"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";

type Props = {
  answer: string | null;
  /** Controlled override from a parent "expand all" toggle. */
  expandAll?: boolean;
};

export function AnswerBlock({ answer, expandAll }: Props) {
  const [open, setOpen] = useState(false);

  // Parent "expand all" toggle overrides local state when it changes.
  useEffect(() => {
    if (expandAll !== undefined) setOpen(expandAll);
  }, [expandAll]);

  if (!answer) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-accent-ink transition hover:underline"
      >
        <Sparkles className="h-3 w-3" />
        AI 解答
        <ChevronDown className={cn("h-3 w-3 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="prose-il mt-2 max-w-[68ch] border-l-2 border-accent/30 pl-3">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
