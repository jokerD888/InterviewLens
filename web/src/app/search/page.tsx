"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Loader2 } from "lucide-react";
import { QuestionCard } from "@/components/question-card";
import { SearchBar } from "@/components/search-bar";
import { fetcher, type Question } from "@/lib/api";

export default function SearchPage() {
  const router = useRouter();
  const search = useSearchParams();
  const initialQ = search.get("q") ?? "";
  const initialCompany = search.get("company") ?? "";
  const initialPosition = search.get("position") ?? "";

  const [submitted, setSubmitted] = useState(initialQ);
  const [company, setCompany] = useState(initialCompany);
  const [position, setPosition] = useState(initialPosition);
  const [minQuality, setMinQuality] = useState(0);

  // Mirror state -> URL
  useEffect(() => {
    const sp = new URLSearchParams();
    if (submitted) sp.set("q", submitted);
    if (company) sp.set("company", company);
    if (position) sp.set("position", position);
    if (minQuality > 0) sp.set("min_quality", String(minQuality));
    const qs = sp.toString();
    router.replace(`/search${qs ? "?" + qs : ""}`, { scroll: false });
  }, [submitted, company, position, minQuality, router]);

  const url =
    submitted.trim().length >= 2
      ? `/posts/search?${new URLSearchParams({
          q: submitted,
          ...(company ? { company } : {}),
          ...(position ? { position } : {}),
          ...(minQuality > 0 ? { min_quality: String(minQuality) } : {}),
          limit: "30",
        }).toString()}`
      : null;

  const { data, error, isLoading } = useSWR<Question[]>(url, fetcher);

  return (
    <div className="mx-auto max-w-screen-xl space-y-4 p-4">
      <SearchBar initial={submitted} onSubmit={setSubmitted} />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Filter label="公司" value={company} placeholder="字节跳动" onChange={setCompany} />
        <Filter label="岗位" value={position} placeholder="后端开发" onChange={setPosition} />
        <Filter
          label="最低分"
          value={String(minQuality || "")}
          placeholder="0-100"
          onChange={(v) => setMinQuality(Number(v) || 0)}
          width="w-20"
        />
        <ExampleQueries onPick={setSubmitted} />
      </div>

      {!submitted && (
        <p className="rounded border border-dashed border-border p-6 text-center text-sm text-muted">
          输入关键词，例如 “分布式锁实现” “JVM 老年代 GC” “TCP 三次握手”，按回车搜索
        </p>
      )}

      {submitted && isLoading && (
        <div className="flex items-center gap-2 p-4 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> 检索中…
        </div>
      )}
      {error && <div className="p-4 text-sm text-bad">加载失败：{(error as Error).message}</div>}

      {data && (
        <div className="space-y-2">
          <p className="text-xs text-muted">{data.length} 条结果</p>
          {data.map((q) => (
            <QuestionCard key={q.id} q={q} highlight={submitted} />
          ))}
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
    <label className="inline-flex items-center gap-1 rounded border border-border bg-panel px-2 py-1">
      <span className="text-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`bg-transparent outline-none placeholder:text-muted/60 ${width ?? "w-32"}`}
      />
    </label>
  );
}

function ExampleQueries({ onPick }: { onPick: (q: string) => void }) {
  const examples = ["分布式锁", "Redis 持久化", "MySQL 索引", "JVM GC", "Transformer"];
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-muted">示例：</span>
      {examples.map((e) => (
        <button
          key={e}
          onClick={() => onPick(e)}
          className="rounded-full border border-border px-2 py-0.5 hover:border-accent hover:text-accent"
        >
          {e}
        </button>
      ))}
    </div>
  );
}
