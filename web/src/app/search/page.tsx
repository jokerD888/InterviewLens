"use client";

import { useState } from "react";
import useSWR from "swr";
import { Loader2 } from "lucide-react";
import { QuestionCard } from "@/components/question-card";
import { SearchBar } from "@/components/search-bar";
import { fetcher, type Question } from "@/lib/api";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [minQuality, setMinQuality] = useState(0);

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
      <SearchBar
        initial={q}
        onSubmit={(v) => {
          setQ(v);
          setSubmitted(v);
        }}
      />
      <div className="flex flex-wrap gap-2 text-xs">
        <Filter label="公司" value={company} placeholder="字节跳动" onChange={setCompany} />
        <Filter label="岗位" value={position} placeholder="后端开发" onChange={setPosition} />
        <Filter
          label="最低分"
          value={String(minQuality || "")}
          placeholder="0-100"
          onChange={(v) => setMinQuality(Number(v) || 0)}
          width="w-20"
        />
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
