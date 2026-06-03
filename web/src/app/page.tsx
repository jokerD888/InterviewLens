"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { CompanyList } from "@/components/company-list";
import { PositionFilter } from "@/components/position-filter";
import { SummaryView } from "@/components/summary-view";
import { fetcher, type Company } from "@/lib/api";

export default function HomePage() {
  const [companyName, setCompanyName] = useState<string | null>(null);
  const [positionName, setPositionName] = useState<string | null>(null);
  const [period, setPeriod] = useState<string>("all");

  const { data: companies } = useSWR<Company[]>(
    "/companies?with_counts=true&limit=200",
    fetcher,
  );
  const companyId = useMemo(
    () => companies?.find((c) => c.canonical === companyName)?.id ?? null,
    [companies, companyName],
  );

  return (
    <div className="mx-auto grid max-w-screen-2xl grid-cols-12 gap-4 p-4">
      <aside className="col-span-3 space-y-3">
        <h2 className="text-xs uppercase tracking-wider text-muted">公司</h2>
        <div className="rounded-lg border border-border bg-panel/40 p-2">
          <CompanyList selected={companyName} onSelect={(c) => {
            setCompanyName(c);
            setPositionName(null);
          }} />
        </div>
      </aside>

      <section className="col-span-9 space-y-4">
        <div className="flex items-center justify-between">
          <PositionFilter
            companyId={companyId}
            selected={positionName}
            onSelect={setPositionName}
          />
          <PeriodPicker value={period} onChange={setPeriod} />
        </div>

        <div className="rounded-lg border border-border bg-panel/40 p-5">
          <SummaryView company={companyName} position={positionName} period={period} />
        </div>
      </section>
    </div>
  );
}

function PeriodPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const options = ["all", "2025Q4", "2025Q3", "2025Q2", "2025Q1", "2024Q4"];
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded border border-border bg-panel px-2 py-1 text-xs"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}
