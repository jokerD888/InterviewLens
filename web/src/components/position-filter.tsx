"use client";

import useSWR from "swr";
import { fetcher, paths } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  companyId?: number | null;
  selected?: string | null;
  onSelect: (canonical: string | null) => void;
};

export function PositionFilter({ companyId, selected, onSelect }: Props) {
  // Company picked → its scoped positions; otherwise the global list.
  const url = companyId ? paths.companyPositions(companyId) : paths.positions();
  const { data, isLoading } = useSWR<unknown[]>(url, fetcher);

  if (isLoading) {
    return <div className="h-7 w-64 animate-pulse rounded-full bg-sunk/70" />;
  }
  const items = (data ?? []) as {
    position_name?: string;
    canonical?: string;
    post_count: number | null;
  }[];

  return (
    <div className="flex flex-wrap items-center gap-1.5">
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
