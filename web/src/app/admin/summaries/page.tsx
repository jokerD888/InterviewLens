"use client";
import { Suspense } from "react";
import useSWR from "swr";
import { useSearchParams } from "next/navigation";
import { AdminGate } from "@/components/admin-access";
import { AdminSummaryBrowser } from "@/components/admin-summary-browser";
import { fetcher, paths, type Company } from "@/lib/api";

function Archive() {
  const search = useSearchParams();
  const { data } = useSWR<Company[]>(paths.companies(), fetcher);
  return <AdminSummaryBrowser initialCompanies={data ?? []} initialCompany={search.get("company")} initialPosition={search.get("position")} initialPeriod={search.get("period") ?? "all"} />;
}
export default function AdminSummariesPage() {
  return <AdminGate><p className="px-6 pt-4 text-sm text-muted">历史摘要仅供管理核对，尚未重新编纂，不对外展示。</p><Suspense fallback={<p>载入…</p>}><Archive /></Suspense></AdminGate>;
}
