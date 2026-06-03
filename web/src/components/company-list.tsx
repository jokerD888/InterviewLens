"use client";

import useSWR from "swr";
import { fetcher, type Company } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  selected?: string | null;
  onSelect: (canonical: string | null) => void;
};

export function CompanyList({ selected, onSelect }: Props) {
  const { data, error, isLoading } = useSWR<Company[]>(
    "/companies?with_counts=true&limit=200",
    fetcher,
  );

  if (isLoading) return <Skeleton n={10} />;
  if (error)
    return (
      <div className="text-sm text-bad">公司列表加载失败：{(error as Error).message}</div>
    );

  return (
    <div className="space-y-1">
      <button
        onClick={() => onSelect(null)}
        className={cn(
          "flex w-full items-center justify-between rounded px-2 py-1.5 text-sm",
          "hover:bg-panel",
          !selected && "bg-panel font-medium",
        )}
      >
        <span>全部公司</span>
        <span className="text-xs text-muted">{data?.length ?? 0}</span>
      </button>
      {(data ?? []).map((c) => (
        <button
          key={c.id}
          onClick={() => onSelect(c.canonical)}
          className={cn(
            "flex w-full items-center justify-between rounded px-2 py-1.5 text-sm",
            "hover:bg-panel",
            selected === c.canonical && "bg-panel font-medium text-accent",
          )}
        >
          <span className="truncate">{c.canonical}</span>
          <span className="ml-2 text-xs text-muted">{c.post_count ?? 0}</span>
        </button>
      ))}
    </div>
  );
}

function Skeleton({ n }: { n: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="h-7 animate-pulse rounded bg-panel/60" />
      ))}
    </div>
  );
}
