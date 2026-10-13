"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { CompanyList } from "@/components/company-list";
import { PositionBrowser } from "@/components/position-browser";
import type { Company } from "@/lib/api";
type Props = {
  initialCompanies: Company[];
  initialCompany: string | null;
  initialPosition: string | null;
  initialPeriod: string;
  apiDown?: boolean;
};
export function BrowserShell({ initialCompanies, initialCompany, apiDown }: Props) {
  const router = useRouter();
  const [company, setCompany] = useState(initialCompany);
  useEffect(() => {
    router.replace((company ? `/?company=${encodeURIComponent(company)}` : "/") as Route, { scroll: false });
  }, [company, router]);
  return <div className="mx-auto grid max-w-screen-2xl grid-cols-12 gap-8 px-6 py-6">
    <aside className="col-span-12 lg:col-span-3">
      <div className="mb-2 flex justify-between border-b border-ink/30 pb-1 text-xs">
        <h2>公司目录</h2><span className="text-muted">{apiDown ? "暂时无法加载" : `${initialCompanies.length} 家`}</span>
      </div>
      <div className="max-h-[calc(100vh-13rem)] overflow-y-auto">
        <CompanyList selected={company} onSelect={setCompany} />
      </div>
    </aside>
    <section className="col-span-12 lg:col-span-9">
      <PositionBrowser key={company ?? "all"} company={company} />
    </section>
  </div>;
}
