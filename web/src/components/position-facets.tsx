"use client";

import useSWR from "swr";
import { fetcher, paths, type PositionFacets, type PositionTaxonomy } from "@/lib/api";
import { cn } from "@/lib/cn";

export const EMPTY_FACETS: PositionFacets = {
  positionCategory: null, specializations: [], domains: [], skills: [],
};

export function PositionFacetFilter({ value, onChange }: {
  value: PositionFacets; onChange: (value: PositionFacets) => void;
}) {
  const { data, error, mutate } = useSWR<PositionTaxonomy>(paths.positionTaxonomy(), fetcher);
  if (error) return <p role="alert">岗位分类加载失败。<button onClick={() => void mutate()}>重试</button></p>;
  if (!data) return <p className="text-sm text-muted">加载岗位分类…</p>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" aria-label="一级岗位分类">
        {["全部", ...data.categories].map((category) => (
          <button key={category} type="button"
            aria-pressed={(value.positionCategory ?? "全部") === category}
            onClick={() => onChange({ ...value, positionCategory: category === "全部" ? null : category })}
            className={cn("rounded-full border px-3 py-1 text-xs",
              (value.positionCategory ?? "全部") === category ? "border-accent bg-accent text-bg" : "border-rule/60 text-muted")}
          >{category}</button>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        {([['specializations', '技术方向'], ['domains', '业务领域'], ['skills', '技术栈']] as const).map(([field, label]) => (
          <details key={field} className="relative min-w-36 rounded border border-rule/60 px-3 py-2">
            <summary className="cursor-pointer text-sm">{label}{value[field].length ? ` (${value[field].length})` : ""}</summary>
            <div className="mt-2 max-h-48 min-w-44 space-y-1 overflow-y-auto">
              {data[field].map((option) => (
                <label key={option} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={value[field].includes(option)}
                    onChange={(event) => onChange({ ...value, [field]: event.target.checked
                      ? [...value[field], option] : value[field].filter((v) => v !== option) })} />
                  {option}
                </label>
              ))}
            </div>
          </details>
        ))}
      </div>

    </div>
  );
}
