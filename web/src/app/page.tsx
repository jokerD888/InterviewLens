import { Suspense } from "react";
import { BrowserShell } from "@/components/browser-shell";

export default function HomePage() {
  return (
    <Suspense fallback={<BrowserLoading />}>
      <BrowserShell />
    </Suspense>
  );
}

function BrowserLoading() {
  return (
    <div className="mx-auto grid max-w-screen-2xl grid-cols-12 gap-8 px-6 py-6" aria-busy="true">
      <aside className="col-span-12 lg:col-span-3">
        <h2 className="mb-2 border-b border-ink/30 pb-1 text-xs">公司目录</h2>
        <div className="space-y-1.5 p-1">
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="h-7 animate-pulse rounded bg-sunk/70" />
          ))}
        </div>
      </aside>
      <section className="col-span-12 lg:col-span-9">
        <p role="status" className="text-sm text-muted">加载面经…</p>
      </section>
    </div>
  );
}
