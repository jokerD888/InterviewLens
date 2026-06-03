"use client";

import useSWR from "swr";
import { fetcher, type Position } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  companyId?: number | null;
  selected?: string | null;
  onSelect: (canonical: string | null) => void;
};

export function PositionFilter({ companyId, selected, onSelect }: Props) {
  // When a company is picked we go through /companies/{id}/positions.
  // Otherwise show the global /positions list.
  const url = companyId
    ? `/companies/${companyId}/positions`
    : "/positions?with_counts=true&limit=200";
  const { data, isLoading } = useSWR<unknown[]>(url, fetcher);

  if (isLoading) {
    return <div className="h-8 animate-pulse rounded bg-panel/60" />;
  }
  const items = (data ?? []) as { position_name?: string; canonical?: string; post_count: number | null }[];

  return (
    <div className="flex flex-wrap gap-1.5">
      <Chip active={!selected} onClick={() => onSelect(null)}>
        全部岗位
      </Chip>
      {items.map((p, i) => {
        const name = (p.position_name ?? p.canonical) as string;
        return (
          <Chip
            key={i}
            active={selected === name}
            onClick={() => onSelect(name)}
            count={p.post_count ?? undefined}
          >
            {name}
          </Chip>
        );
      })}
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
        "rounded-full border px-2.5 py-0.5 text-xs transition",
        active
          ? "border-accent bg-accent/10 text-accent"
          : "border-border bg-panel text-muted hover:text-ink",
      )}
    >
      {children}
      {count != null && <span className="ml-1.5 opacity-60">{count}</span>}
    </button>
  );
}
