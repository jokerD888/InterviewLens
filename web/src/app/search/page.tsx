"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import useSWR from "swr";
import { Loader2, BookOpen, CheckCircle, XCircle } from "lucide-react";
import { QuestionCard } from "@/components/question-card";
import { SearchBar } from "@/components/search-bar";
import { BridgeModal, type AnswerItem } from "@/components/bridge-modal";
import { fetcher, paths, bridge, type Question } from "@/lib/api";

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="px-6 py-6 font-mono text-xs uppercase tracking-widest text-muted">载入…</div>}>
      <SearchInner />
    </Suspense>
  );
}

function SearchInner() {
  const router = useRouter();
  const search = useSearchParams();
  const initialQ = search.get("q") ?? "";

  const [submitted, setSubmitted] = useState(initialQ);
  const [company, setCompany] = useState(search.get("company") ?? "");
  const [position, setPosition] = useState(search.get("position") ?? "");
  const [minQuality, setMinQuality] = useState(Number(search.get("min_quality")) || 0);

  // Mirror state -> URL
  useEffect(() => {
    const sp = new URLSearchParams();
    if (submitted) sp.set("q", submitted);
    if (company) sp.set("company", company);
    if (position) sp.set("position", position);
    if (minQuality > 0) sp.set("min_quality", String(minQuality));
    const qs = sp.toString();
    router.replace(`/search${qs ? "?" + qs : ""}` as Route, { scroll: false });
  }, [submitted, company, position, minQuality, router]);

  const url =
    submitted.trim().length >= 2
      ? paths.search({ q: submitted, company, position, minQuality, limit: 30 })
      : null;

  const { data, error, isLoading } = useSWR<Question[]>(url, fetcher);
  const [expandAll, setExpandAll] = useState<boolean | undefined>(undefined);

  // --- bridge state ---
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bridgeState, setBridgeState] = useState<"idle" | "generating" | "preview" | "exporting">("idle");
  const [previewAnswers, setPreviewAnswers] = useState<AnswerItem[]>([]);
  const [bridgeError, setBridgeError] = useState<string | null>(null);
  const [bridgeResult, setBridgeResult] = useState<{ imported: number; skipped: number } | null>(null);

  const toggleQ = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll = () => data && setSelectedIds(new Set(data.map((q) => q.id)));
  const clearAll = () => setSelectedIds(new Set());

  const handleBridge = async () => {
    if (selectedIds.size === 0) return;
    setBridgeState("generating");
    setBridgeError(null);
    try {
      const resp = await bridge.generateAnswers([...selectedIds]);
      const items: AnswerItem[] = resp.answers
        .filter((a) => a.generated_answer)
        .map((a) => ({
          question_id: a.question_id,
          content: a.content,
          category: a.category,
          generated_answer: a.generated_answer!,
          importance_score: a.importance_score,
          source_url: null, // ponytail: source_url not passed through generate-answers yet
        }));
      if (items.length === 0) {
        setBridgeError("未能生成任何答案，请重试");
        setBridgeState("idle");
        return;
      }
      setPreviewAnswers(items);
      setBridgeState("preview");
    } catch (e) {
      setBridgeError(`生成失败：${(e as Error).message}`);
      setBridgeState("idle");
    }
  };

  const handleConfirm = async (edited: AnswerItem[]) => {
    setBridgeState("exporting");
    try {
      const resp = await bridge.export(
        edited.map((a) => ({
          question: a.content,
          answer: a.generated_answer,
          importance_score: a.importance_score,
        }))
      );
      setBridgeResult({ imported: resp.imported, skipped: resp.skipped });
    } catch (e) {
      setBridgeError(`导入失败：${(e as Error).message}`);
    } finally {
      setBridgeState("idle");
      setPreviewAnswers([]);
      setSelectedIds(new Set());
    }
  };

  const handleCloseModal = () => {
    setBridgeState("idle");
    setPreviewAnswers([]);
  };

  return (
    <div className="mx-auto max-w-screen-xl space-y-5 px-6 py-6">
      <div className="rise rise-1">
        <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.3em] text-accent">语义检索</p>
        <SearchBar initial={submitted} onSubmit={setSubmitted} />
      </div>

      <div className="rise rise-2 flex flex-wrap items-center gap-2">
        <Filter label="公司" value={company} placeholder="字节跳动" onChange={setCompany} />
        <Filter label="岗位" value={position} placeholder="后端开发" onChange={setPosition} />
        <Filter
          label="最低分"
          value={String(minQuality || "")}
          placeholder="0–100"
          onChange={(v) => setMinQuality(Number(v) || 0)}
          width="w-16"
        />
        <ExampleQueries onPick={setSubmitted} />
      </div>

      {/* --- result toast --- */}
      {bridgeResult && (
        <div className="rise rise-2 flex items-center gap-3 rounded-sm border border-good/40 bg-good/10 px-5 py-3">
          <CheckCircle className="h-5 w-5 text-good" />
          <div className="font-mono text-xs text-ink">
            成功导入 <span className="tabular-nums font-bold text-good">{bridgeResult.imported}</span> 张卡片
            {bridgeResult.skipped > 0 && (
              <span className="text-muted">，跳过 <span className="tabular-nums">{bridgeResult.skipped}</span> 张</span>
            )}
          </div>
          <button
            onClick={() => setBridgeResult(null)}
            className="ml-auto font-mono text-[10px] text-muted hover:text-ink"
          >
            关闭
          </button>
        </div>
      )}

      {/* --- bridge error --- */}
      {bridgeError && (
        <div className="rise rise-2 flex items-center gap-3 rounded-sm border border-bad/40 bg-bad/10 px-5 py-3">
          <XCircle className="h-5 w-5 text-bad" />
          <p className="font-mono text-xs text-bad">{bridgeError}</p>
          <button
            onClick={() => setBridgeError(null)}
            className="ml-auto font-mono text-[10px] text-muted hover:text-ink"
          >
            关闭
          </button>
        </div>
      )}

      {!submitted && (
        <p className="rise rise-3 border border-dashed border-rule/70 px-6 py-10 text-center font-serif text-[15px] text-muted">
          输入关键词检索，例如{" "}
          <em className="text-accent-ink">"分布式锁实现"</em>、
          <em className="text-accent-ink">"JVM 老年代 GC"</em>、
          <em className="text-accent-ink">"TCP 三次握手"</em> — 按回车搜索。
        </p>
      )}

      {submitted && isLoading && (
        <div className="flex items-center gap-2 p-4 font-mono text-xs uppercase tracking-widest text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> 检索中…
        </div>
      )}
      {error && <div className="p-4 font-mono text-sm text-bad">加载失败：{(error as Error).message}</div>}

      {data && (
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-ink/25 pb-1">
            <p className="font-mono text-[11px] uppercase tracking-widest text-muted">
              <span className="tabular-nums text-ink">{data.length}</span> 条结果
            </p>
            {/* --- batch toolbar --- */}
            {data.length > 0 && (
              <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-widest">
                <button onClick={selectAll} className="text-muted hover:text-ink transition">
                  全选
                </button>
                {selectedIds.size > 0 && (
                  <>
                    <button onClick={clearAll} className="text-muted hover:text-ink transition">
                      取消
                    </button>
                    <span className="tabular-nums text-ink">{selectedIds.size} 个</span>
                    <button
                      onClick={handleBridge}
                      disabled={bridgeState === "generating" || bridgeState === "exporting"}
                      className="inline-flex items-center gap-1 rounded-sm bg-accent-ink px-3 py-1 text-bg transition hover:bg-accent disabled:opacity-40"
                    >
                      {bridgeState === "generating" ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin" /> 生成中…
                        </>
                      ) : bridgeState === "exporting" ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin" /> 导入中…
                        </>
                      ) : (
                        <>
                          <BookOpen className="h-3 w-3" /> 加入八股
                        </>
                      )}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          {data.some((q) => q.answer_ai) && (
            <button
              onClick={() => setExpandAll((v) => !v)}
              className="font-mono text-[10px] uppercase tracking-widest text-accent-ink hover:underline"
            >
              {expandAll ? "收起所有答案" : "展开所有答案"}
            </button>
          )}
          {data.map((q) => (
            <QuestionCard
              key={q.id}
              q={q}
              highlight={submitted}
              expandAll={expandAll}
              selected={selectedIds.has(q.id)}
              onToggle={() => toggleQ(q.id)}
            />
          ))}
          {data.length === 0 && (
            <p className="py-8 text-center font-serif text-muted">没有命中，换个说法或放宽筛选试试。</p>
          )}
        </div>
      )}

      {/* --- bridge preview modal --- */}
      {bridgeState === "preview" && previewAnswers.length > 0 && (
        <BridgeModal
          answers={previewAnswers}
          loading={false}
          onClose={handleCloseModal}
          onConfirm={handleConfirm}
        />
      )}
    </div>
  );
}

function Filter({
  label,
  value,
  placeholder,
  onChange,
  width,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
  width?: string;
}) {
  return (
    <label className="inline-flex items-center gap-2 border-b border-rule/60 px-1 py-0.5 font-mono text-[11px] uppercase tracking-wider transition focus-within:border-accent">
      <span className="text-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`bg-transparent normal-case tracking-normal text-ink outline-none placeholder:text-muted/50 ${width ?? "w-28"}`}
      />
    </label>
  );
}

function ExampleQueries({ onPick }: { onPick: (q: string) => void }) {
  const examples = ["分布式锁", "Redis 持久化", "MySQL 索引", "JVM GC", "Transformer"];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted">示例</span>
      {examples.map((e) => (
        <button
          key={e}
          onClick={() => onPick(e)}
          className="rounded-full border border-rule/60 px-2.5 py-0.5 font-serif text-[13px] text-muted transition hover:border-accent hover:text-accent-ink"
        >
          {e}
        </button>
      ))}
    </div>
  );
}
