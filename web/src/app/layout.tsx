import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "InterviewLens",
  description: "Aggregate Nowcoder interview experiences with a LangGraph agent pipeline",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className="dark">
      <body className="min-h-screen bg-bg text-ink antialiased">
        <div className="flex min-h-screen flex-col">
          <Header />
          <main className="flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}

function Header() {
  return (
    <header className="border-b border-border bg-panel/50 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-screen-2xl items-center justify-between px-6">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 rounded bg-accent" />
          <span className="text-sm font-medium tracking-wide">InterviewLens</span>
          <span className="ml-2 text-xs text-muted">面经聚合 · LangGraph Agent</span>
        </div>
        <nav className="flex items-center gap-4 text-xs">
          <Link href="/">浏览</Link>
          <Link href="/search">搜索</Link>
          <Link href="/admin">管理</Link>
          <a
            href="https://github.com/jokerD888/InterviewLens"
            target="_blank"
            rel="noreferrer"
            className="text-muted hover:text-ink"
          >
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}

import Link from "next/link";
