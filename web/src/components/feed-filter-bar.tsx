"use client";

import useSWR from "swr";
import { fetcher, paths, type Company } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PositionFilter } from "@/components/position-filter";

const CATEGORIES = [
  { label: "全部", value: null },
  { label: "校招", value: "校招" },
  { label: "社招", value: "社招" },
  { label: "实习", value: "实习" },
];

type Props = {
  company: string | null;
  position: string | null;
  category: string | null;
  onCompanyChange: (canonical: string | null) => void;
  onPositionChange: (canonical: string | null) => void;
  onCategoryChange: (category: string | null) => void;
};

export function FeedFilterBar({
  company,
  position,
  category,
  onCompanyChange,
  onPositionChange,
  onCategoryChange,
}: Props) {
  const { data: companies } = useSWR<Company[]>(paths.companies(), fetcher);

  const companyId = (companies ?? []).find((c) => c.canonical === company)?.id ?? null;

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Company select */}
      <select
        value={company ?? ""}
        onChange={(e) => {
          onCompanyChange(e.target.value || null);
          onPositionChange(null); // reset position when company changes
        }}
        className={cn(
          "border-b border-rule/60 bg-transparent px-1 py-1 font-mono text-[11px] uppercase tracking-wide text-ink",
          "focus:border-accent focus:outline-none",
          "[&_option]:bg-bg [&_option]:text-ink",
        )}
      >
        <option value="">全部公司</option>
        {(companies ?? []).map((c) => (
          <option key={c.id} value={c.canonical}>
            {c.canonical}
            {c.post_count != null ? ` (${c.post_count})` : ""}
          </option>
        ))}
      </select>

      {/* Position filter chips (reuses existing component) */}
      <PositionFilter
        companyId={companyId}
        selected={position}
        onSelect={onPositionChange}
      />

      {/* Category chips */}
      <div className="flex items-center gap-1.5">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.label}
            onClick={() => onCategoryChange(cat.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[11px] uppercase tracking-wide transition",
              category === cat.value
                ? "border-accent bg-accent text-bg shadow-sm"
                : "border-rule/60 bg-transparent text-muted hover:border-ink hover:text-ink",
            )}
          >
            {cat.label}
          </button>
        ))}
      </div>
    </div>
  );
}
