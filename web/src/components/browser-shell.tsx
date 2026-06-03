"use client";

// Client shell that owns the interactive state of the home page.
// State is mirrored into the URL via history.replaceState so users can share
// links like /?company=字节跳动&position=后端开发&period=2025Q2.

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CompanyList } from "@/components/company-list";
import { PositionFilter } from "@/components/position-filter";
import { SummaryView } from "@/components/summary-view";
import type { Company } from "@/lib/api";

type Props = {
  initialCompanies: Company[];
  initialCompany: string | null;
  initialPosition: string | null;
  initialPeriod: string;
  apiDown?: boolean;
};

export function BrowserShell({
  initialCompanies,
  initialCompany,
  initialPosition,
  initialPeriod,
  apiDown,
}: Props) {
  const router = useRouter();
  const search = useSearchParams();

  const [companyName, setCompanyName] = useState<string | null>(initialCompany);
  const [positionName, setPositionName] = useState<string | null>(initialPosition);
  const [period, setPeriod] = useState<string>(initialPeriod);

  // Sync state -> URL (replaceState avoids history pollution)
  useEffect(() => {
    const sp = new URLSearchParams();
    if (companyName) sp.set("company", companyName);
    if (positionName) sp.set("position", positionName);
    if (period && period !== "all") sp.set("period", period);
    const qs = sp.toString();
    const next = qs ? `?${qs}` : "/";
    if (next !== `?${search.toString()}` && next !== "/" + search.toString()) {
      router.replace(`/${qs ? "?" + qs : ""}`, { scroll: false });
    }
  }, [companyName, positionName, period, router, search]);

  const companyId = useMemo(
    () => initialCompanies.find((c) => c.canonical === companyName)?.id ?? null,
    [initialCompanies, companyName],
  );

  return (
    <div className="mx-auto grid max-w-screen-2xl grid-cols-12 gap-4 p-4">
      <aside className="col-span-3 space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-xs uppercase tracking-wider text-muted">公司</h2>
          {apiDown && (
            <span className="text-xs text-bad">API 未连通</span>
          )}
        </div>
        <div className="rounded-lg border border-border bg-panel/40 p-2">
          <CompanyList
            selected={companyName}
            onSelect={(c) => {
              setCompanyName(c);
              setPositionName(null);
            }}
          />
        </div>
      </aside>

      <section className="col-span-9 space-y-4">
        <div className="flex items-center justify-between gap-2">
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
