"use client";

import { useState } from "react";
import { X, Loader2, Sparkles, Send } from "lucide-react";

export type AnswerItem = {
  question_id: number;
  content: string;
  category: string | null;
  generated_answer: string;
  importance_score: number;
  source_url: string | null;
};

type Props = {
  answers: AnswerItem[];
  loading: boolean;
  onClose: () => void;
  onConfirm: (answers: AnswerItem[]) => void;
};

export function BridgeModal({ answers, loading, onClose, onConfirm }: Props) {
  const [edits, setEdits] = useState<Record<number, string>>({});

  const getAnswerText = (item: AnswerItem) =>
    edits[item.question_id] !== undefined
      ? edits[item.question_id]
      : item.generated_answer;

  const confirmed = answers.map((a) => ({
    ...a,
    generated_answer: getAnswerText(a),
  }));

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 pt-[5vh]">
      <div className="mx-4 w-full max-w-3xl rounded-lg border border-border bg-bg shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-accent-ink" />
            <span className="font-mono text-[11px] uppercase tracking-widest text-ink">
              AI 答案预览 · 确认后导入每日八股
            </span>
          </div>
          <button onClick={onClose} className="text-muted hover:text-ink transition">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="max-h-[60vh] space-y-5 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center gap-2 py-12 font-mono text-xs text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> AI 正在生成答案…
            </div>
          ) : (
            confirmed.map((item) => (
              <div key={item.question_id} className="border-b border-border pb-4 last:border-0">
                <div className="mb-2 flex items-start justify-between gap-4">
                  <p className="font-serif text-[16px] leading-relaxed text-ink">
                    {item.content}
                  </p>
                  <span className="shrink-0 rounded-sm bg-ink px-2 py-0.5 font-mono text-[10px] text-bg">
                    ★ {item.importance_score}
                  </span>
                </div>
                {item.category && (
                  <span className="mb-2 inline-block font-mono text-[10px] uppercase tracking-wider text-muted">
                    {item.category}
                  </span>
                )}
                <textarea
                  value={getAnswerText(item)}
                  onChange={(e) =>
                    setEdits({ ...edits, [item.question_id]: e.target.value })
                  }
                  className="mt-1 w-full resize-y rounded-sm border border-border bg-panel p-3 font-serif text-[15px] leading-relaxed text-ink focus:border-accent focus:outline-none"
                  rows={4}
                />
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4">
          <button
            onClick={onClose}
            className="font-mono text-[10px] uppercase tracking-widest text-muted hover:text-ink transition"
          >
            取消
          </button>
          <button
            onClick={() => onConfirm(confirmed)}
            disabled={loading || answers.length === 0}
            className="inline-flex items-center gap-1.5 rounded-sm bg-accent-ink px-4 py-2 font-mono text-[10px] uppercase tracking-widest text-bg transition hover:bg-accent disabled:opacity-40"
          >
            <Send className="h-3 w-3" />
            确认导入（{confirmed.length} 张卡片）
          </button>
        </div>
      </div>
    </div>
  );
}
