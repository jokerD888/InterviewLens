import type { Metadata, Route } from "next";
import Link from "next/link";
import Image from "next/image";
import "./globals.css";
import { ThemeToggle } from "../components/theme-toggle";

export const metadata: Metadata = {
  metadataBase: new URL("https://interview.819266.xyz"),
  title: "InterviewLens — 面经档案馆",
  description: "聚合公开面经，按公司与岗位方向浏览，通过语义检索查找面试问题。",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "16x16 32x32 48x48", type: "image/x-icon" },
      { url: "/favicon.svg", sizes: "any", type: "image/svg+xml" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  manifest: "/site.webmanifest",
  openGraph: {
    type: "website", locale: "zh_CN", siteName: "InterviewLens",
    title: "InterviewLens — 面经档案馆",
    description: "聚合公开面经，按公司与岗位方向浏览，通过语义检索查找面试问题。",
    images: [{ url: "/brand/share-card.png", width: 1200, height: 630, alt: "InterviewLens 面经档案馆" }],
  },
  twitter: {
    card: "summary_large_image", title: "InterviewLens — 面经档案馆",
    images: ["/brand/share-card.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        {/* Apply persisted/system theme before paint to avoid a flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('il-theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();",
          }}
        />
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
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-end justify-between gap-x-6 gap-y-3 px-6 pb-2 pt-4">
        <div className="flex items-baseline gap-4">
          <Link href="/" aria-label="InterviewLens 首页" className="group flex items-center gap-2.5">
            <Image src="/brand/logo.svg" alt="" width={40} height={40} unoptimized className="h-8 w-8 shrink-0 sm:h-10 sm:w-10" />
            <span className="font-display text-xl font-black leading-none tracking-masthead text-ink sm:text-2xl">
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
          <a
            href="https://github.com/jokerD888/InterviewLens"
            target="_blank"
            rel="noreferrer"
            className="ml-2 border-b border-transparent px-2 py-1 text-muted transition hover:border-ink hover:text-ink"
          >
            GitHub ↗
          </a>
          <ThemeToggle />
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
        <span className="inline-flex items-center gap-2">
          <Image src="/brand/logo.svg" alt="" width={20} height={20} unoptimized />
          InterviewLens · 面试学习参考
        </span>
        <span className="text-muted/70">
          题目整理自公开面经，详情保留原帖链接；AI 答案仅供参考。
        </span>
      </div>
    </footer>
  );
}
