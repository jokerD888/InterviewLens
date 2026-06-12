"use client";

// Client shell owning the interactive state of the home page. State mirrors
// into the URL via router.replace so links like
// /?company=字节跳动&position=后端开发&period=2025Q2 are shareable.

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import useSWR from "swr";
import { CompanyList } from "@/components/company-list";
import { PositionFilter } from "@/components/position-filter";
import { SummaryView } from "@/components/summary-view";
import { fetcher, paths, type Company, type Summary } from "@/lib/api";

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

  // Sync state -> URL (replace avoids history pollution)
  useEffect(() => {
    const sp = new URLSearchParams();
    if (companyName) sp.set("company", companyName);
    if (positionName) sp.set("position", positionName);
    if (period && period !== "all") sp.set("period", period);
    const qs = sp.toString();
    const next = qs ? `?${qs}` : "/";
    if (next !== `?${search.toString()}` && next !== "/" + search.toString()) {
      router.replace(`/${qs ? "?" + qs : ""}` as Route, { scroll: false });
    }
  }, [companyName, positionName, period, router, search]);

  const companyId = useMemo(
    () => initialCompanies.find((c) => c.canonical === companyName)?.id ?? null,
    [initialCompanies, companyName],
  );

  const totalPosts = useMemo(
    () => initialCompanies.reduce((acc, c) => acc + (c.post_count ?? 0), 0),
    [initialCompanies],
  );

  const hasSelection = Boolean(companyName && positionName);

  return (
    <div className="mx-auto grid max-w-screen-2xl grid-cols-12 gap-x-8 gap-y-4 px-6 py-6">
      {/* ── Left rail: company catalog ─────────────────────────────── */}
      <aside className="rise rise-1 col-span-12 lg:col-span-3">
        <div className="mb-2 flex items-baseline justify-between border-b border-ink/30 pb-1">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.22em] text-ink">公司目录</h2>
          {apiDown ? (
            <span className="font-mono text-[10px] uppercase tracking-wider text-bad">API 未连通</span>
          ) : (
            <span className="font-mono text-[10px] tabular-nums text-muted">
              {initialCompanies.length} 家 · {totalPosts} 帖
            </span>
          )}
        </div>
        <div className="max-h-[calc(100vh-13rem)] overflow-y-auto pr-1">
          <CompanyList
            selected={companyName}
            onSelect={(c) => {
              setCompanyName(c);
              setPositionName(null);
            }}
          />
        </div>
      </aside>

      {/* ── Main column: positions + summary OR recent index ───────── */}
      <section className="rise rise-2 col-span-12 space-y-5 lg:col-span-9">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/30 pb-3">
          <PositionFilter companyId={companyId} selected={positionName} onSelect={setPositionName} />
          <PeriodPicker value={period} onChange={setPeriod} />
        </div>

        <div className="min-h-[24rem] bg-panel/50 p-6 shadow-card ring-1 ring-border">
          <SummaryView company={companyName} position={positionName} period={period} />
        </div>

        {!hasSelection && (
          <RecentSummaries
            onPick={(s) => {
              setCompanyName(s.company);
              setPositionName(s.position);
              setPeriod(s.period);
            }}
          />
        )}
      </section>
    </div>
  );
}

function PeriodPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const options = ["all", "2025Q4", "2025Q3", "2025Q2", "2025Q1", "2024Q4"];
  return (
    <label className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted">
      周期
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border-b border-ink/40 bg-transparent py-0.5 font-mono text-[11px] uppercase tracking-wider text-ink outline-none focus:border-accent"
      >
        {options.map((o) => (
          <option key={o} value={o} className="bg-bg">
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Recent-summary index — surfaces GET /summaries as a clickable shortcut grid. */
function RecentSummaries({ onPick }: { onPick: (s: Summary) => void }) {
  const { data } = useSWR<Summary[]>(paths.summaries({ limit: 9 }), fetcher);
  if (!data || data.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 flex items-baseline gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-muted">
        <span className="text-accent">¶</span> 最近编纂
      </h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {data.map((s) => (
          <button
            key={s.id}
            onClick={() => onPick(s)}
            className="group border border-border bg-panel/40 p-3 text-left transition hover:border-ink hover:bg-panel"
          >
            <div className="font-display text-base font-semibold leading-tight text-ink group-hover:text-accent-ink">
              {s.company}
            </div>
            <div className="mt-0.5 truncate text-sm text-muted">{s.position}</div>
            <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-muted/80">
              <span>{s.period}</span>
              <span className="tabular-nums">{s.sample_count} 题</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
