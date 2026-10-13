"use client";
import { Suspense } from "react";
import { AdminGate } from "@/components/admin-access";
import { SearchInner } from "@/components/search-browser";

export default function AdminSearchPage() {
  return <AdminGate><Suspense fallback={<p>载入…</p>}><SearchInner management /></Suspense></AdminGate>;
}
