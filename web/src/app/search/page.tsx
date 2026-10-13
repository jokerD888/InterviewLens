import { Suspense } from "react";
import { SearchInner } from "@/components/search-browser";
export default function SearchPage() {
  return <Suspense fallback={<p>载入…</p>}><SearchInner /></Suspense>;
}
