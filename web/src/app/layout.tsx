import type { Metadata, Route } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "InterviewLens — 面经档案馆",
  description: "Aggregate Nowcoder interview experiences with a LangGraph agent pipeline",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* Fraunces (display serif), Newsreader (body serif), IBM Plex Mono (chrome),
            Noto Serif SC (CJK). Degrades to Georgia / system serif when offline. */}
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,900;1,9..144,500&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&family=IBM+Plex+Mono:wght@400;500;600&family=Noto+Serif+SC:wght@400;600;900&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-bg text-ink antialiased">
        <div className="flex min-h-screen flex-col">
          <Masthead />
          <main className="flex-1">{children}</main>
          <Colophon />
        </div>
      </body>
    </html>
  );
}

function Masthead() {
  return (
    <header className="border-b-2 border-ink/80 bg-bg">
      <div className="mx-auto flex max-w-screen-2xl items-end justify-between gap-6 px-6 pb-2 pt-4">
        <div className="flex items-baseline gap-4">
          <Link href="/" className="group flex items-baseline gap-3">
            <span className="font-display text-2xl font-black leading-none tracking-masthead text-ink">
              Interview<span className="text-accent">Lens</span>
            </span>
          </Link>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.25em] text-muted sm:inline">
            面经档案馆 · Est. 2026
          </span>
        </div>
        <nav className="flex items-center gap-1 pb-1 font-mono text-[11px] uppercase tracking-widest">
          <NavLink href="/">浏览</NavLink>
          <NavLink href="/feed">最新面经</NavLink>
          <NavLink href="/search">检索</NavLink>
          <NavLink href="/admin">机房</NavLink>
          <a
            href="https://github.com/jokerD888/InterviewLens"
            target="_blank"
            rel="noreferrer"
            className="ml-2 border-b border-transparent px-2 py-1 text-muted transition hover:border-ink hover:text-ink"
          >
            GitHub ↗
          </a>
        </nav>
      </div>
      {/* Sub-rule with a fine editorial double line */}
      <div className="mx-auto max-w-screen-2xl px-6">
        <div className="h-px bg-ink/30" />
      </div>
    </header>
  );
}

function NavLink({ href, children }: { href: Route; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="border-b border-transparent px-2 py-1 text-ink transition hover:border-accent hover:text-accent"
    >
      {children}
    </Link>
  );
}

function Colophon() {
  return (
    <footer className="mt-8 border-t border-border">
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-between gap-2 px-6 py-4 font-mono text-[10px] uppercase tracking-[0.2em] text-muted">
        <span>InterviewLens · 个人用途 · 内容不二次发布</span>
        <span className="text-muted/70">
          Crawler → Cleaner → Extractor → Normalizer → Scorer · LangGraph
        </span>
      </div>
    </footer>
  );
}
