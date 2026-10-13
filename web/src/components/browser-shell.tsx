"use client";
import { useSearchParams } from "next/navigation";
import { CompanyList, useCompanyCatalog } from "@/components/company-list";
import { PositionBrowser } from "@/components/position-browser";

export function BrowserShell() {
  const search = useSearchParams();
  const company = search.get("company") || null;
  const { data, error, isLoading } = useCompanyCatalog();

  function selectCompany(next: string | null) {
    if (next === company) return;
    const url = new URL(window.location.href);
    if (next) url.searchParams.set("company", next);
    else url.searchParams.delete("company");
    // Next synchronizes native history with useSearchParams. Company filters
    // only need client data, so avoid a server navigation for each selection.
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  return <div className="mx-auto grid max-w-screen-2xl grid-cols-12 gap-8 px-6 py-6">
    <aside className="col-span-12 lg:col-span-3">
      <div className="mb-2 flex justify-between border-b border-ink/30 pb-1 text-xs">
        <h2>公司目录</h2><span className="text-muted">{error ? "暂时无法加载" : isLoading ? "加载中…" : `${data?.length ?? 0} 家`}</span>
      </div>
      <div className="max-h-[calc(100vh-13rem)] overflow-y-auto">
        <CompanyList selected={company} onSelect={selectCompany} />
      </div>
    </aside>
    <section className="col-span-12 lg:col-span-9">
      <PositionBrowser key={company ?? "all"} company={company} />
    </section>
  </div>;
}
