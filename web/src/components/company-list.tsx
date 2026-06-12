"use client";

import useSWR from "swr";
import { fetcher, paths, type Company } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  selected?: string | null;
  onSelect: (canonical: string | null) => void;
};

export function CompanyList({ selected, onSelect }: Props) {
  const { data, error, isLoading } = useSWR<Company[]>(paths.companies(), fetcher);

  if (isLoading) return <Skeleton n={12} />;
  if (error)
    return <div className="px-2 py-3 font-mono text-xs text-bad">公司列表加载失败：{(error as Error).message}</div>;

  const list = data ?? [];

  return (
    <ul className="divide-y divide-border/70">
      <Row index={0} active={!selected} label="全部公司" count={list.length} onClick={() => onSelect(null)} />
      {list.map((c, i) => (
        <Row
          key={c.id}
          index={i + 1}
          active={selected === c.canonical}
          label={c.canonical}
          count={c.post_count ?? 0}
          onClick={() => onSelect(c.canonical)}
        />
      ))}
    </ul>
  );
}

function Row({
  index,
  active,
  label,
  count,
  onClick,
}: {
  index: number;
  active?: boolean;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        className={cn(
          "group flex w-full items-center gap-3 px-2 py-1.5 text-left transition",
          active ? "bg-accent/10" : "hover:bg-sunk/60",
        )}
      >
        <span
          className={cn(
            "w-6 shrink-0 text-right font-mono text-[10px] tabular-nums",
            active ? "text-accent" : "text-muted/60",
          )}
        >
          {index === 0 ? "··" : String(index).padStart(2, "0")}
        </span>
        <span
          className={cn(
            "flex-1 truncate font-serif text-[15px] leading-snug",
            active ? "font-medium text-accent-ink" : "text-ink group-hover:text-ink",
          )}
        >
          {label}
        </span>
        <span
          className={cn(
            "shrink-0 font-mono text-[11px] tabular-nums",
            active ? "text-accent" : "text-muted",
          )}
        >
          {count}
        </span>
      </button>
    </li>
  );
}

function Skeleton({ n }: { n: number }) {
  return (
    <div className="space-y-1.5 p-1">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="h-7 animate-pulse rounded bg-sunk/70" />
      ))}
    </div>
  );
}
