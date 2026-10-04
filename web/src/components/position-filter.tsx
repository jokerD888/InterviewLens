"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, paths, type CompanyPositionStat, type Position } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  companyId?: number | null;
  selected?: string | null;
  onSelect: (canonical: string | null) => void;
};

export function PositionFilter({ companyId, selected, onSelect }: Props) {
  // Company picked → its scoped positions; otherwise the global list.
  const url = companyId ? paths.companyPositions(companyId) : paths.positions();
  return <PositionOptions key={url} url={url} selected={selected} onSelect={onSelect} />;
}

function PositionOptions({ url, selected, onSelect }: Props & { url: string }) {
  const { data, error, isLoading, mutate } = useSWR<(Position | CompanyPositionStat)[]>(url, fetcher);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  if (isLoading) {
    return <div className="h-7 w-64 animate-pulse rounded-full bg-sunk/70" />;
  }
  if (error) {
    return (
      <div role="alert" className="text-sm text-bad">
        岗位列表加载失败，请重试。
        <button type="button" onClick={() => void mutate()} className="ml-2 underline">重试</button>
      </div>
    );
  }
  const items = (data ?? []).filter((p) => (p.post_count ?? 0) > 0).map((p) => ({
    name: "position_name" in p ? p.position_name : p.canonical,
    post_count: p.post_count,
  }));
  const term = query.trim().toLocaleLowerCase();
  const matched = items.filter((p) => p.name.toLocaleLowerCase().includes(term));
  const visible = expanded || term ? matched : matched.slice(0, 12);
  const selectedItem = matched.find((p) => p.name === selected);
  if (selectedItem && !visible.includes(selectedItem)) visible.push(selectedItem);

  return (
    <div className="w-full space-y-2">
      <div className="flex items-center gap-3">
        <input
          type="search"
          aria-label="搜索岗位"
          placeholder="搜索岗位"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-48 rounded border border-rule/60 bg-transparent px-2 py-1 text-sm text-ink"
        />
        <span className="text-xs text-muted">{items.length} 个岗位条目</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip active={!selected} onClick={() => onSelect(null)}>
          全部岗位
        </Chip>
        {visible.map((p) => {
          const name = p.name;
          return (
            <Chip
              key={name}
              active={selected === name}
              onClick={() => onSelect(name)}
              count={p.post_count ?? undefined}
            >
              {name}
            </Chip>
          );
        })}
      </div>
      {term && matched.length === 0 && <p className="text-sm text-muted">没有匹配的岗位。</p>}
      {!term && items.length > 12 && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-accent-ink underline"
        >
          {expanded ? "收起岗位" : `展开全部 ${items.length} 个岗位`}
        </button>
      )}
    </div>
  );
}

function Chip({
  children,
  active,
  count,
  onClick,
}: {
  children: React.ReactNode;
  active?: boolean;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[11px] uppercase tracking-wide transition",
        active
          ? "border-accent bg-accent text-bg shadow-sm"
          : "border-rule/60 bg-transparent text-muted hover:border-ink hover:text-ink",
      )}
    >
      {children}
      {count != null && (
        <span className={cn("tabular-nums", active ? "text-bg/75" : "opacity-55")}>{count}</span>
      )}
    </button>
  );
}
