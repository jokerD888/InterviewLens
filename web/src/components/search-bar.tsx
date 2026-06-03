"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

type Props = {
  initial?: string;
  placeholder?: string;
  onSubmit: (q: string) => void;
};

export function SearchBar({ initial = "", placeholder, onSubmit }: Props) {
  const [value, setValue] = useState(initial);

  useEffect(() => setValue(initial), [initial]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const q = value.trim();
        if (q) onSubmit(q);
      }}
      className={cn(
        "flex items-center gap-2 rounded-lg border border-border bg-panel",
        "px-3 py-2 transition focus-within:border-accent",
      )}
    >
      <Search className="h-4 w-4 text-muted" />
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder ?? "搜索面试题（语义检索，例如：分布式锁实现）"}
        className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
      />
      <button
        type="submit"
        className="rounded bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:opacity-90"
      >
        搜索
      </button>
    </form>
  );
}
