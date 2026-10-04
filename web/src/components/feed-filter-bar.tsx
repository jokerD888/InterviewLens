"use client";

import useSWR from "swr";
import { fetcher, paths, type Company, type PositionFacets } from "@/lib/api";
import { PositionFacetFilter } from "@/components/position-facets";

export function FeedFilterBar({ company, onCompanyChange, facets, onFacetsChange }: {
  company: string | null;
  onCompanyChange: (company: string | null) => void;
  facets: PositionFacets;
  onFacetsChange: (facets: PositionFacets) => void;
}) {
  const { data: companies } = useSWR<Company[]>(paths.companies(), fetcher);
  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm text-muted">
        公司
        <select aria-label="公司" value={company ?? ""}
          onChange={(e) => onCompanyChange(e.target.value || null)}
          className="border-b border-rule/60 bg-transparent px-1 py-1 text-ink [&_option]:bg-bg">
          <option value="">全部公司</option>
          {(companies ?? []).map((c) => <option key={c.id} value={c.canonical}>{c.canonical}</option>)}
        </select>
      </label>
      <PositionFacetFilter value={facets} onChange={onFacetsChange} />
    </div>
  );
}
