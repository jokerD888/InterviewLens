"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import useSWR from "swr";
import { Loader2 } from "lucide-react";
import { QuestionCard } from "@/components/question-card";
import { SearchBar } from "@/components/search-bar";
import { fetcher, paths, type Question } from "@/lib/api";

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

      {!submitted && (
        <p className="rise rise-3 border border-dashed border-rule/70 px-6 py-10 text-center font-serif text-[15px] text-muted">
          输入关键词检索，例如{" "}
          <em className="text-accent-ink">“分布式锁实现”</em>、
          <em className="text-accent-ink">“JVM 老年代 GC”</em>、
          <em className="text-accent-ink">“TCP 三次握手”</em> — 按回车搜索。
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
          <p className="border-b border-ink/25 pb-1 font-mono text-[11px] uppercase tracking-widest text-muted">
            <span className="tabular-nums text-ink">{data.length}</span> 条结果
          </p>
          {data.some((q) => q.answer_ai) && (
            <button
              onClick={() => setExpandAll((v) => !v)}
              className="font-mono text-[10px] uppercase tracking-widest text-accent-ink hover:underline"
            >
              {expandAll ? "收起所有答案" : "展开所有答案"}
            </button>
          )}
          {data.map((q) => (
            <QuestionCard key={q.id} q={q} highlight={submitted} expandAll={expandAll} />
          ))}
          {data.length === 0 && (
            <p className="py-8 text-center font-serif text-muted">没有命中，换个说法或放宽筛选试试。</p>
          )}
        </div>
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
