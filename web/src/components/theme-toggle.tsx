"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "il-theme";

/**
 * Sun/moon toggle that flips the `.dark` class on <html> and persists the
 * choice in localStorage. The actual theme is applied pre-hydration by an
 * inline script in layout.tsx (avoids a flash of the wrong theme).
 *
 * To avoid a hydration mismatch, the initial render does NOT read the DOM:
 * both the server and the first client render show the moon icon with a
 * neutral title. The real theme is read in useEffect (after mount) and the
 * icon/title update on the second render — no SSR/CSR diff.
 */
export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const isDark = document.documentElement.classList.contains("dark");
    setTheme(isDark ? "dark" : "light");
    setMounted(true);
  }, []);

  const toggle = () => {
    const next: "light" | "dark" = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode / disabled storage — non-fatal */
    }
    document.documentElement.classList.toggle("dark", next === "dark");
  };

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="切换深色 / 浅色模式"
      title={mounted ? (isDark ? "切换到浅色" : "切换到深色") : "切换主题"}
      className="ml-2 flex h-7 w-7 items-center justify-center rounded-full border border-rule/50 text-muted transition hover:border-ink hover:text-ink"
    >
      {mounted && isDark ? (
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}
